import os
import re
import json
import zlib
import base64
import shutil
import urllib.parse
import urllib.request
import uuid
import math
import hashlib
from datetime import datetime, timezone
import concurrent.futures

this_dir = os.path.dirname(os.path.realpath(__file__))

CHUNK_SIZE = 100 * 1024 * 1024
# there is an upper limit for chunk size on server, ideally should be requested from there once implemented
UPLOAD_CHUNK_SIZE = 10 * 1024 * 1024

IGNORE_EXT = re.compile(r'({})$'.format(
    '|'.join(re.escape(x) for x in ['-shm', '-wal', '~', 'pyc', 'swap'])
))
IGNORE_FILES = ['.DS_Store', '.directory']


def ignore_file(filename):
    name, ext = os.path.splitext(filename)
    if ext and IGNORE_EXT.search(ext):
        return True
    if filename in IGNORE_FILES:
        return True
    return False


try:
    import dateutil.parser
    from dateutil.tz import tzlocal
except ImportError:
    # this is to import all dependencies shipped with package (e.g. to use in qgis-plugin)
    deps_dir = os.path.join(this_dir, 'deps')
    if os.path.exists(deps_dir):
        import sys
        for f in os.listdir(os.path.join(deps_dir)):
            sys.path.append(os.path.join(deps_dir, f))

        import dateutil.parser
        from dateutil.tz import tzlocal

from .utils import save_to_file, generate_checksum, move_file, DateTimeEncoder


class InvalidProject(Exception):
    pass

class ClientError(Exception):
    pass


def find(items, fn):
    for item in items:
        if fn(item):
            return item


# TODO: maybe following functions (or some of them) could be
# encapsulated in the new MerginProject class

def list_project_directory(directory):
    prefix = os.path.abspath(directory) # .rstrip(os.path.sep)
    proj_files = []
    excluded_dirs = ['.mergin']
    for root, dirs, files in os.walk(directory, topdown=True):
        dirs[:] = [d for d in dirs if d not in excluded_dirs]
        for file in files:
            if not ignore_file(file):
                abs_path = os.path.abspath(os.path.join(root, file))
                rel_path = os.path.relpath(abs_path, start=prefix)
                # we need posix path
                proj_path = '/'.join(rel_path.split(os.path.sep))
                proj_files.append({
                    "path": proj_path,
                    "checksum": generate_checksum(abs_path),
                    "size": os.path.getsize(abs_path),
                    "mtime": datetime.fromtimestamp(os.path.getmtime(abs_path), tzlocal())
                })
    return proj_files


def project_changes(origin, current):
    origin_map = {f["path"]: f for f in origin}
    current_map = {f["path"]: f for f in current}
    removed = [f for f in origin if f["path"] not in current_map]
    added = [f for f in current if f["path"] not in origin_map]

    # updated = list(filter(
    #     lambda f: f["path"] in origin_map and f["checksum"] != origin_map[f["path"]]["checksum"],
    #     current
    # ))
    updated = []
    for f in current:
        path = f["path"]
        if path in origin_map and f["checksum"] != origin_map[path]["checksum"]:
            updated.append(f)

    moved = []
    for rf in removed:
        match = find(
            current,
            lambda f: f["checksum"] == rf["checksum"] and f["size"] == rf["size"] and all(f["path"] != mf["path"] for mf in moved)
        )
        if match:
            moved.append({**rf, "new_path": match["path"]})

    added = [f for f in added if all(f["path"] != mf["new_path"] for mf in moved)]
    removed = [f for f in removed if all(f["path"] != mf["path"] for mf in moved)]

    return {
        "renamed": moved,
        "added": added,
        "removed": removed,
        "updated": updated
    }

def inspect_project(directory):
    meta_dir = os.path.join(directory, '.mergin')
    info_file = os.path.join(meta_dir, 'mergin.json')
    if not os.path.exists(meta_dir) or not os.path.exists(info_file):
        raise InvalidProject(directory)

    with open(info_file, 'r') as f:
        return json.load(f)

def save_project_file(project_directory, data):
    meta_dir = os.path.join(project_directory, '.mergin')
    if not os.path.exists(meta_dir):
        os.makedirs(meta_dir)

    project_file = os.path.join(meta_dir, 'mergin.json')
    with open(project_file, 'w') as f:
        json.dump(data, f, indent=2)

def decode_token_data(token):
    token_prefix = "Bearer ."
    if not token.startswith(token_prefix):
        raise ValueError("Invalid token type")

    try:
        data = token[len(token_prefix):].split('.')[0]
        # add proper base64 padding"
        data += "=" * (-len(data) % 4)
        decoded = zlib.decompress(base64.urlsafe_b64decode(data))
        return json.loads(decoded)
    except (IndexError, TypeError, ValueError):
        raise ValueError("Invalid token data")


class MerginClient:
    min_server_version = '2019.3-22'

    def __init__(self, url, auth_token=None, login=None, password=None):
        self.url = url

        self._auth_params = None
        self._auth_session = None
        self._user_info = None
        if auth_token:
            token_data = decode_token_data(auth_token)
            self._auth_session = {
                "token": auth_token,
                "expire": dateutil.parser.parse(token_data["expire"])
            }
            self._user_info = {
                "username": token_data["username"]
            }

        self.opener = urllib.request.build_opener()
        urllib.request.install_opener(self.opener)

        if login and password:
            self.login(login, password)

    def _do_request(self, request):
        if self._auth_session:
            delta = self._auth_session["expire"] - datetime.now(timezone.utc)
            if delta.total_seconds() < 1:
                self._auth_session = None
                # Refresh auth token when login credentials are available
                if self._auth_params:
                    self.login(self._auth_params["login"], self._auth_params["password"])

            if self._auth_session:
                request.add_header("Authorization", self._auth_session["token"])
        try:
            return self.opener.open(request)
        except urllib.error.HTTPError as e:
            if e.headers.get("Content-Type", "") == "application/problem+json":
                info = json.load(e)
                raise ClientError(info.get("detail"))
            raise ClientError(e.read().decode("utf-8"))

    def get(self, path, data=None, headers={}):
        url = urllib.parse.urljoin(self.url, urllib.parse.quote(path))
        if data:
            url += "?" + urllib.parse.urlencode(data)
        request = urllib.request.Request(url, headers=headers)
        return self._do_request(request)

    def post(self, path, data=None, headers={}):
        url = urllib.parse.urljoin(self.url, urllib.parse.quote(path))
        if headers.get("Content-Type", None) == "application/json":
            data = json.dumps(data, cls=DateTimeEncoder).encode("utf-8")
        request = urllib.request.Request(url, data, headers, method="POST")
        return self._do_request(request)

    def server_version(self):
        """
        Return version of the server

        rtype: String
        """
        resp = self.get("/ping")
        try:
            data = json.load(resp)
            return data["version"]
        except:
            raise ClientError("Unknown server")

    def check_version(self):
        """
        Test whether version of the server meets the minimum required value

        rtype: Boolean
        """
        server_version = self.server_version()

        if server_version == "dev":
            return True

        def parse_version(string):
            m = re.match("^(\d+).(\d+)-(\d+)", string)
            if m:
                return list(map(int, m.groups()))

        try:
            s1, s2, s3 = parse_version(server_version)
            m1, m2, m3 = parse_version(self.min_server_version)
            return s1 > m1 or (s1 == m1 and (s2 > m2 or (s2 == m2 and s3 >= m3)))
        except (TypeError, ValueError):
            raise ClientError("Unknown server version: %s" % server_version)

    def login(self, login, password):
        """
        Authenticate login credentials and store session token

        :param login: User's username of email address
        :type login: String

        :param password: User's password
        :type password: String
        """
        params = {
            "login": login,
            "password": password
        }
        self._auth_params = params
        resp = self.post("/v1/auth/login", params, {"Content-Type": "application/json"})
        data = json.load(resp)
        session = data["session"]
        self._auth_session = {
            "token": "Bearer %s" % session["token"],
            "expire": dateutil.parser.parse(session["expire"])
        }
        self._user_info = {
            "username": data["username"]
        }
        return session

    def create_project(self, project_name, directory=None, is_public=False):
        """
        Create new project repository on Mergin server, optionally initialized from given local directory.

        :param project_name: Project name
        :type project_name: String

        :param directory: Local project directory, defaults to None
        :type directory: String

        :param is_public: Flag for public/private project, defaults to False
        :type directory: Boolean
        """
        if not self._user_info:
            raise Exception("Authentication required")
        if directory and not os.path.exists(directory):
            raise Exception("Project directory does not exists")

        params = {
            "name": project_name,
            "public": is_public
        }
        namespace = self._user_info["username"]
        self.post("/v1/project/%s" % namespace, params, {"Content-Type": "application/json"})
        data = {
            "name": "%s/%s" % (namespace, project_name),
            "version": "v0",
            "files": []
        }
        if directory:
            save_project_file(directory, data)
            if len(os.listdir(directory)) > 1:
                self.push_project(directory)

    def projects_list(self, tags=None, user=None, flag=None, q=None):
        """
        Find all available mergin projects.

        :param tags: Filter projects by tags ('valid_qgis', 'mappin_use', input_use')
        :type tags: List

        :param user: Username for 'flag' filter. If not provided, it means user executing request.
        :type user: String

        :param flag: Predefined filter flag ('created', 'shared')
        :type flag: String

        :param q: Search query string
        :type q: String

        :rtype: List[Dict]
        """
        params = {}
        if tags:
            params["tags"] = ",".join(tags)
        if user:
            params["user"] = user
        if flag:
            params["flag"] = flag
        if q:
            params["q"] = q
        resp = self.get("/v1/project", params)
        projects = json.load(resp)
        return projects

    def project_info(self, project_path):
        """
        Fetch info about project.

        :param project_path: Project's full name (<namespace>/<name>)
        :type project_path: String

        :rtype: Dict
        """
        resp = self.get("/v1/project/{}".format(project_path))
        return json.load(resp)

    def project_versions(self, project_path):
        """
        Get records of all project's versions (history).

        :param project_path: Project's full name (<namespace>/<name>)
        :type project_path: String

        :rtype: List[Dict]
        """
        resp = self.get("/v1/project/version/{}".format(project_path))
        return json.load(resp)

    def download_project(self, project_path, directory, parallel=True):
        """
        Download latest version of project into given directory.

        :param project_path: Project's full name (<namespace>/<name>)
        :type project_path: String

        :param directory: Target directory
        :type directory: String

        :param parallel: Use multi-thread approach to download files in parallel requests, default True
        :type parallel: Boolean
        """
        if os.path.exists(directory):
            raise Exception("Project directory already exists")
        os.makedirs(directory)

        project_info = self.project_info(project_path)
        version = project_info['version'] if project_info['version'] else 'v0'

        # sending parallel requests is good for projects with a lot of small files
        if parallel:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures_map = {}
                for file in project_info['files']:
                    future = executor.submit(self._download_file, project_path, version, file, directory, parallel)
                    futures_map[future] = file

                for future in concurrent.futures.as_completed(futures_map):
                    file = futures_map[future]
                    try:
                        future.result(60)
                    except concurrent.futures.TimeoutError:
                        raise ClientError("Timeout error: failed to download {}".format(file))
        else:
            for file in project_info['files']:
                    self._download_file(project_path, version, file, directory, parallel)

        data = {
            "name": project_path,
            "version": version,
            "files": project_info["files"]
        }
        save_project_file(directory, data)

    def push_project(self, directory, parallel=True):
        """
        Upload local changes to the repository.

        :param directory: Project's directory
        :type directory: String
        :param parallel: Use multi-thread approach to upload files in parallel requests, defaults to True
        :type parallel: Boolean
        """
        local_info = inspect_project(directory)
        project_path = local_info["name"]
        server_info = self.project_info(project_path)
        server_version = server_info["version"] if server_info["version"] else "v0"
        if local_info.get("version", "v0") != server_version:
            raise ClientError("Update your local repository")

        files = list_project_directory(directory)
        changes = project_changes(server_info["files"], files)
        if all(len(changes[key]) == 0 for key in changes.keys()):
            return

        upload_files = changes["added"] + changes["updated"]
        for f in upload_files:
            f["chunks"] = [str(uuid.uuid4()) for i in range(math.ceil(f["size"] / UPLOAD_CHUNK_SIZE))]

        data = {
            "version": local_info.get("version"),
            "changes": changes
        }
        resp = self.post("/v1/project/push/%s" % project_path, data, {"Content-Type": "application/json"})
        info = json.load(resp)

        # upload files' chunks and close transaction
        if upload_files:
            if parallel:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures_map = {}
                    for file in upload_files:
                        future = executor.submit(self._upload_file, info["transaction"], directory, file, parallel)
                        futures_map[future] = file

                    for future in concurrent.futures.as_completed(futures_map):
                        file = futures_map[future]
                        try:
                            future.result(60)
                        except concurrent.futures.TimeoutError:
                            raise ClientError("Timeout error: failed to upload {}".format(file))
            else:
                for file in upload_files:
                    self._upload_file(info["transaction"], directory, file, parallel)

            try:
                resp = self.post("/v1/project/push/finish/%s" % info["transaction"])
                info = json.load(resp)
            except ClientError:
                self.post("/v1/project/push/cancel/%s" % info["transaction"])
                raise

        local_info["files"] = info["files"]
        local_info["version"] = info["version"]
        save_project_file(directory, local_info)

    def pull_project(self, directory, parallel=True):
        """
        Fetch and apply changes from repository.

        :param directory: Project's directory
        :type directory: String
        :param parallel: Use multi-thread approach to fetch files in parallel requests, defaults to True
        :type parallel: Boolean
        """

        local_info = inspect_project(directory)
        project_path = local_info["name"]
        server_info = self.project_info(project_path)

        if local_info["version"] == server_info["version"]:
            return # Project is up to date

        files = list_project_directory(directory)
        local_changes = project_changes(files, local_info["files"])
        pull_changes = project_changes(local_info["files"], server_info["files"])

        def local_path(path):
            return os.path.join(directory, path)

        locally_modified = list(
            [f["path"] for f in local_changes["added"] + local_changes["updated"]] + \
            [f["new_path"] for f in local_changes["renamed"]]
        )

        def backup_if_conflict(path, checksum):
            if path in locally_modified:
                current_file = find(files, lambda f: f["path"] == path)
                if current_file["checksum"] != checksum:
                    backup_path = local_path("{}_conflict_copy".format(path))
                    index = 2
                    while os.path.exists(backup_path):
                        backup_path = local_path("{}_conflict_copy{}".format(path, index))
                        index += 1
                    # it is unnecessary to copy conflicted file, it would be better to simply rename it
                    shutil.copy(local_path(path), backup_path)

        fetch_files = pull_changes["added"] + pull_changes["updated"]
        if fetch_files:
            temp_dir = os.path.join(directory, '.mergin', 'fetch_{}-{}'.format(local_info["version"], server_info["version"]))
            # sending parallel requests is good for projects with a lot of small files
            if parallel:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures_map = {}
                    for file in fetch_files:
                        future = executor.submit(project_path, server_info['version'], file, temp_dir, parallel)
                        futures_map[future] = file

                    for future in concurrent.futures.as_completed(futures_map):
                        file = futures_map[future]
                        try:
                            future.result(60)
                        except concurrent.futures.TimeoutError:
                            raise ClientError("Timeout error: failed to download {}".format(file))
                        src = os.path.join(temp_dir, file["path"])
                        dest = local_path(file["path"])
                        backup_if_conflict(file["path"], file["checksum"])
                        move_file(src, dest)
            else:
                for file in fetch_files:
                    self._download_file(project_path, server_info['version'], file, temp_dir, parallel)
                    src = os.path.join(temp_dir, file["path"])
                    dest = local_path(file["path"])
                    backup_if_conflict(file["path"], file["checksum"])
                    move_file(src, dest)
            shutil.rmtree(temp_dir)

        for file in pull_changes["removed"]:
            backup_if_conflict(file["path"], file["checksum"])
            os.remove(local_path(file["path"]))

        for file in pull_changes["renamed"]:
            backup_if_conflict(file["new_path"], file["checksum"])
            move_file(local_path(file["path"]), local_path(file["new_path"]))

        local_info["files"] = server_info["files"]
        local_info["version"] = server_info["version"] if server_info["version"] else 'v0'
        save_project_file(directory, local_info)

    def _download_file(self, project_path, project_version, file, directory, parallel=True):
        """
        Helper to download single project file from server in chunks.

        :param project_path: Project's full name (<namespace>/<name>)
        :type project_path: String
        :param project_version: Version of the project (v<n>)
        :type project_version: String
        :param file: File metadata item from Project['files']
        :type file: dict
        :param directory: Project's directory
        :type directory: String
        :param parallel: Use multi-thread approach to download parts in parallel requests, default True
        :type parallel: Boolean
        """
        query_params = {
            "file": file['path'],
            "version": project_version
        }
        file_dir = os.path.dirname(os.path.normpath(os.path.join(directory, file['path'])))
        basename = os.path.basename(file['path'])

        def download_file_part(part):
            """Callback to get a part of file using request to server with Range header."""
            start = part * (1 + CHUNK_SIZE)
            range_header = {"Range": "bytes={}-{}".format(start, start + CHUNK_SIZE)}
            resp = self.get("/v1/project/raw/{}".format(project_path), data=query_params, headers=range_header)
            if resp.status in [200, 206]:
                save_to_file(resp, os.path.join(file_dir, basename + ".{}".format(part)))
            else:
                raise ClientError('Failed to download part {} of file {}'.format(part, basename))

        # download large files in chunks is beneficial mostly for retry on failure
        chunks = math.ceil(file['size'] / CHUNK_SIZE)
        if parallel:
            # create separate n threads, default as cores * 5
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures_map = {executor.submit(download_file_part, i): i for i in range(chunks)}
                for future in concurrent.futures.as_completed(futures_map):
                    i = futures_map[future]
                    try:
                        future.result(60)
                    except concurrent.futures.TimeoutError:
                        raise ClientError('Timeout error: failed to download part {} of file {}'.format(i, basename))
        else:
            for i in range(chunks):
                download_file_part(i)

        # merge chunks together
        with open(os.path.join(file_dir, basename), 'wb') as final:
            for i in range(chunks):
                file_part = os.path.join(directory, file['path'] + ".{}".format(i))
                with open(file_part, 'rb') as chunk:
                    shutil.copyfileobj(chunk, final)
                os.remove(file_part)

    def delete_project(self, project_path):
        """
        Delete project repository on server.

        :param project_path: Project's full name (<namespace>/<name>)
        :type project_path: String

        """
        path = "/v1/project/%s" % project_path
        url = urllib.parse.urljoin(self.url, urllib.parse.quote(path))
        request = urllib.request.Request(url, method="DELETE")
        self._do_request(request)

    def _upload_file(self, transaction, project_dir, file_meta, parallel=True):
        """
        Upload file in open upload transaction.

        :param transaction: transaction uuid
        :type transaction: String
        :param project_dir: local project directory
        :type project_dir: String
        :param file_meta: metadata for file to upload
        :type file_meta: Dict
        :param parallel: Use multi-thread approach to upload file chunks in parallel requests, defaults to True
        :type parallel: Boolean
        :raises ClientError: raise on data integrity check failure
        """
        headers = {"Content-Type": "application/octet-stream"}
        file_path = os.path.join(project_dir, file_meta["path"])

        def upload_chunk(chunk_id, data):
            checksum = hashlib.sha1()
            checksum.update(data)
            size = len(data)
            resp = self.post("/v1/project/push/chunk/{}/{}".format(transaction, chunk_id), data, headers)
            data = json.load(resp)
            if not (data['size'] == size and data['checksum'] == checksum.hexdigest()):
                self.post("/v1/project/push/cancel/{}".format(transaction))
                raise ClientError("Mismatch between uploaded file chunk {} and local one".format(chunk))

        with open(file_path, 'rb') as file:
            if parallel:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures_map = {executor.submit(upload_chunk, chunk, file.read(UPLOAD_CHUNK_SIZE)): chunk for chunk in file_meta["chunks"]}
                    for future in concurrent.futures.as_completed(futures_map):
                        chunk = futures_map[future]
                        try:
                            future.result(60)
                        except concurrent.futures.TimeoutError:
                            raise ClientError('Timeout error: failed to upload chunk {}'.format(chunk))
            else:
                for chunk in file_meta["chunks"]:
                    data = file.read(UPLOAD_CHUNK_SIZE)
                    upload_chunk(chunk, data)