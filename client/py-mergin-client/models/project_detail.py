# coding: utf-8

"""
    Mergin

    This is a simple Mergin src.  # noqa: E501

    OpenAPI spec version: 0.1
    
    Generated by: https://github.com/swagger-api/swagger-codegen.git
"""


import pprint
import re  # noqa: F401

import six

from py-mergin-client.models.file_info import FileInfo  # noqa: F401,E501
from py-mergin-client.models.project import Project  # noqa: F401,E501
from py-mergin-client.models.project_storage_params import ProjectStorageParams  # noqa: F401,E501


class ProjectDetail(object):
    """NOTE: This class is auto generated by the swagger code generator program.

    Do not edit the class manually.
    """

    """
    Attributes:
      swagger_types (dict): The key is attribute name
                            and the value is attribute type.
      attribute_map (dict): The key is attribute name
                            and the value is json key in definition.
    """
    swagger_types = {
        'name': 'str',
        'storage_params': 'ProjectStorageParams',
        'created': 'datetime',
        'files': 'list[FileInfo]'
    }

    attribute_map = {
        'name': 'name',
        'storage_params': 'storage_params',
        'created': 'created',
        'files': 'files'
    }

    def __init__(self, name=None, storage_params=None, created=None, files=None):  # noqa: E501
        """ProjectDetail - a model defined in Swagger"""  # noqa: E501

        self._name = None
        self._storage_params = None
        self._created = None
        self._files = None
        self.discriminator = None

        self.name = name
        if storage_params is not None:
            self.storage_params = storage_params
        if created is not None:
            self.created = created
        if files is not None:
            self.files = files

    @property
    def name(self):
        """Gets the name of this ProjectDetail.  # noqa: E501


        :return: The name of this ProjectDetail.  # noqa: E501
        :rtype: str
        """
        return self._name

    @name.setter
    def name(self, name):
        """Sets the name of this ProjectDetail.


        :param name: The name of this ProjectDetail.  # noqa: E501
        :type: str
        """
        if name is None:
            raise ValueError("Invalid value for `name`, must not be `None`")  # noqa: E501

        self._name = name

    @property
    def storage_params(self):
        """Gets the storage_params of this ProjectDetail.  # noqa: E501


        :return: The storage_params of this ProjectDetail.  # noqa: E501
        :rtype: ProjectStorageParams
        """
        return self._storage_params

    @storage_params.setter
    def storage_params(self, storage_params):
        """Sets the storage_params of this ProjectDetail.


        :param storage_params: The storage_params of this ProjectDetail.  # noqa: E501
        :type: ProjectStorageParams
        """

        self._storage_params = storage_params

    @property
    def created(self):
        """Gets the created of this ProjectDetail.  # noqa: E501


        :return: The created of this ProjectDetail.  # noqa: E501
        :rtype: datetime
        """
        return self._created

    @created.setter
    def created(self, created):
        """Sets the created of this ProjectDetail.


        :param created: The created of this ProjectDetail.  # noqa: E501
        :type: datetime
        """

        self._created = created

    @property
    def files(self):
        """Gets the files of this ProjectDetail.  # noqa: E501


        :return: The files of this ProjectDetail.  # noqa: E501
        :rtype: list[FileInfo]
        """
        return self._files

    @files.setter
    def files(self, files):
        """Sets the files of this ProjectDetail.


        :param files: The files of this ProjectDetail.  # noqa: E501
        :type: list[FileInfo]
        """

        self._files = files

    def to_dict(self):
        """Returns the model properties as a dict"""
        result = {}

        for attr, _ in six.iteritems(self.swagger_types):
            value = getattr(self, attr)
            if isinstance(value, list):
                result[attr] = list(map(
                    lambda x: x.to_dict() if hasattr(x, "to_dict") else x,
                    value
                ))
            elif hasattr(value, "to_dict"):
                result[attr] = value.to_dict()
            elif isinstance(value, dict):
                result[attr] = dict(map(
                    lambda item: (item[0], item[1].to_dict())
                    if hasattr(item[1], "to_dict") else item,
                    value.items()
                ))
            else:
                result[attr] = value

        return result

    def to_str(self):
        """Returns the string representation of the model"""
        return pprint.pformat(self.to_dict())

    def __repr__(self):
        """For `print` and `pprint`"""
        return self.to_str()

    def __eq__(self, other):
        """Returns true if both objects are equal"""
        if not isinstance(other, ProjectDetail):
            return False

        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        """Returns true if both objects are not equal"""
        return not self == other
