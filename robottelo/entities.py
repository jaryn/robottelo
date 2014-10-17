"""This module defines all entities which Foreman exposes.

Each class in this module corresponds to a certain type of Foreman entity. For
example, :class:`robottelo.entities.Host` corresponds to the "Host" Foreman
entity. Similarly, each class attribute corresponds to a Foreman entity
attribute. For example, the ``Host.name`` class attribute corresponds to the
"name" attribute of a "Host" entity.

Many of these classes contain an inner class named ``Meta``. This inner class
contains any information about an entity that is not a field. That is, the
inner class contains non-field information. This information is especially
useful to :class:`robottelo.factory.EntityFactoryMixin`.

"""
from datetime import datetime
from fauxfactory import gen_alpha, gen_alphanumeric, gen_url
from robottelo.api import client
from robottelo.common.constants import (
    FAKE_1_YUM_REPO, OPERATING_SYSTEMS, VALID_GPG_KEY_FILE)
from robottelo.common.decorators import bz_bug_is_open
from robottelo.common.helpers import (
    get_data_file, get_server_credentials, escape_search)
from robottelo import factory, orm
from time import sleep
import httplib
import random
# (no-init) pylint:disable=W0232
# (too-few-public-methods) pylint:disable=R0903
# (too-many-lines) pylint:disable=C0302


class APIResponseError(Exception):
    """Indicates an error if response returns unexpected result."""


class ActivationKey(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Activtion Key entity."""
    organization = orm.OneToOneField('Organization', required=True)
    name = orm.StringField(required=True)
    description = orm.StringField()
    environment = orm.OneToOneField('Environment')
    content_view = orm.OneToOneField('ContentView')
    unlimited_content_hosts = orm.BooleanField()
    max_content_hosts = orm.IntegerField()
    host_collection = orm.OneToManyField('HostCollection')

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/activation_keys'
        server_modes = ('sat', 'sam')

    def read_raw(self, auth=None):
        super_read_raw = super(ActivationKey, self).read_raw
        response = super_read_raw(auth)
        if response.status_code is 404 and bz_bug_is_open(1127335):
            # Give elasticsearch a chance to index new activation keys.
            sleep(5)
            response = super_read_raw(auth)
        return response

    def path(self, which=None):
        """Extend the default implementation of
        :meth:`robottelo.orm.Entity.path`.

        The format of the returned path depends on the value of ``which``:

        releases
            /activation_keys/<id>/releases
        subscriptions
            /activation_keys/<id>/subscriptions

        ``super`` is called otherwise.

        """
        if which in ('releases', 'subscriptions',):
            return '{0}/{1}'.format(
                super(ActivationKey, self).path(which='self'),
                which
            )
        return super(ActivationKey, self).path(which)

    def add_subsciptions(self, subscription_id, quantity):
        """Helper for adding subscriptions to activation key.

        :returns: The server's response, with all JSON decoded.
        :rtype: dict
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        response = client.post(
            self.path('subscriptions'),
            auth=get_server_credentials(),
            verify=False,
            data={u'id': subscription_id,
                  u'quantity': quantity,}
        )
        response.raise_for_status()
        return response.json()

class Architecture(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Architecture entity."""
    name = orm.StringField(required=True)
    operatingsystem = orm.OneToManyField('OperatingSystem', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/architectures'
        server_modes = ('sat')

    # NOTE: See BZ 1151220
    def create(self, auth=None, data=None):
        """Extend the implementation of
        :meth:`robottelo.factory.Factory.create`.

        Clients must submit a nested hash of attributes when creating an
        architecture. For example, this will not work correctly::

            {'name': 'foo', 'operatingsystem_ids': [1, 2, 3]}

        However, this will work correctly::

            {'architecture': {'name': 'foo', 'operatingsystem_ids': [1, 2, 3]}}

        """
        if data is None:
            data = {u'architecture': self.build(auth=auth)}
        return super(Architecture, self).create(auth, data)

    # NOTE: See BZ 1151240
    def read(self, auth=None, entity=None, attrs=None):
        """Override the default implementation of
        :meth:`robottelo.orm.EntityReadMixin.read`.

        An architecture points to zero or more operating systems.
        Unfortunately, the API communicates the list of pointed-to operating
        systems as a list of hashes named "operatingsystems"::

            {
                u'name': u'i386',
                u'operatingsystems': [
                    {u'id': 1, u'name': u'rhel65'},
                    {u'id': 2, u'name': u'rhel7'},
                ]
            }

        This is incorrect behaviour. The API _should_ return a list of IDs
        named "operatingsystem_ids"::

            {u'name': u'i386', u'operatingsystem_ids': [1, 2]}

        """
        if attrs is None:
            attrs = self.read_json(auth)
        attrs['operatingsystem_ids'] = [
            operatingsystem['id']
            for operatingsystem
            in attrs.pop('operatingsystems')
        ]
        return super(Architecture, self).read(auth, entity, attrs)


class AuthSourceLDAP(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a AuthSourceLDAP entity."""
    account = orm.StringField(null=True)
    attr_photo = orm.StringField(null=True)
    base_dn = orm.StringField(null=True)
    host = orm.StringField(required=True, len=(1, 60))
    name = orm.StringField(required=True, len=(1, 60))
    onthefly_register = orm.BooleanField(null=True)
    port = orm.IntegerField(null=True)  # default: 389
    tls = orm.BooleanField(null=True)

    # required if onthefly_register is true
    account_password = orm.StringField(null=True)
    attr_firstname = orm.StringField(null=True)
    attr_lastname = orm.StringField(null=True)
    attr_login = orm.StringField(null=True)
    attr_mail = orm.EmailField(null=True)

    def _factory_data(self):
        """Customize the data provided to :class:`robottelo.factory.Factory`.

        If ``onthefly_register is True``, several other fields must also be
        filled in.

        """
        values = super(AuthSourceLDAP, self)._factory_data()
        cls = type(self)
        if ('onthefly_register' in values.keys() and
                values['ontheflyregister'] is True):
            values['account_password'] = cls.account_password.get_value()
            values['attr_firstname'] = cls.attr_firstname.get_value()
            values['attr_lastname'] = cls.attr_lastname.get_value()
            values['attr_login'] = cls.attr_login.get_value()
            values['attr_mail'] = cls.attr_mail.get_value()
        return values

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/auth_source_ldaps'
        server_modes = ('sat')


class Bookmark(orm.Entity):
    """A representation of a Bookmark entity."""
    name = orm.StringField(required=True)
    controller = orm.StringField(required=True)
    query = orm.StringField(required=True)
    public = orm.BooleanField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/bookmarks'
        server_modes = ('sat')


class CommonParameter(orm.Entity):
    """A representation of a Common Parameter entity."""
    name = orm.StringField(required=True)
    value = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/common_parameters'
        server_modes = ('sat')


class ComputeAttribute(orm.Entity):
    """A representation of a Compute Attribute entity."""
    compute_profile = orm.OneToOneField('ComputeProfile', required=True)
    compute_resource = orm.OneToOneField('ComputeResource', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/compute_attributes'
        # Alternative paths:
        #
        # '/api/v2/compute_resources/:compute_resource_id/compute_profiles/'
        # ':compute_profile_id/compute_attributes',
        #
        # '/api/v2/compute_profiles/:compute_profile_id/compute_resources/'
        # ':compute_resource_id/compute_attributes',
        #
        # '/api/v2/compute_resources/:compute_resource_id/'
        # 'compute_attributes',
        #
        # '/api/v2/compute_profiles/:compute_profile_id/compute_attributes',
        server_modes = ('sat')


class ComputeProfile(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Compute Profile entity."""
    name = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/compute_profiles'
        server_modes = ('sat')


class ComputeResource(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Compute Resource entity."""
    description = orm.StringField(null=True)
    # `name` cannot contain whitespace. Thus, the chosen string types.
    name = orm.StringField(null=True, str_type=('alphanumeric', 'cjk'))
    password = orm.StringField(null=True)
    provider = orm.StringField(
        null=True,
        required=True,
        choices=('EC2', 'GCE', 'Libvirt', 'Openstack', 'Ovirt', 'Rackspace',
                 'Vmware')
    )
    region = orm.StringField(null=True)
    server = orm.StringField(null=True)
    tenant = orm.StringField(null=True)
    url = orm.URLField(required=True)
    user = orm.StringField(null=True)
    uuid = orm.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/compute_resources'
        server_modes = ('sat')

    def _factory_data(self):
        """Customize the data provided to :class:`robottelo.factory.Factory`.

        Depending upon the value of ``self.provider``, various other fields are
        filled in with values too.

        """
        values = super(ComputeResource, self)._factory_data()
        cls = type(self)
        provider = values['provider']
        # Generate required fields according to the provider. First check if
        # the field is already set by the user, if not generate a random value
        if provider == 'EC2' or provider == 'Ovirt' or provider == 'Openstack':
            for field in ('name', 'password', 'user'):
                if values.get(field) is None:
                    values[field] = getattr(cls, field).get_value()
        elif provider == 'GCE':
            if values.get('name') is None:
                values['name'] = cls.name.get_value()
            # values['email'] = cls.email.get_value()
            # values['key_path'] = cls.key_path.get_value()
            # values['project'] = cls.project.get_value()
            #
            # FIXME: These three pieces of data are required. However, the API
            # docs don't even mention their existence!
            #
            # 1. Figure out valid values for these three fields.
            # 2. Uncomment the above.
            # 3. File an issue on bugzilla asking for the docs to be expanded.
        elif provider == 'Libvirt':
            if values.get('name') is None:
                values['name'] = cls.name.get_value()
        elif provider == 'Rackspace':
            # FIXME: Foreman always returns this error:
            #
            #     undefined method `upcase' for nil:NilClass
            #
            # 1. File a bugzilla issue asking for a fix.
            # 2. Figure out what data is necessary and add it here.
            pass
        elif provider == 'Vmware':
            for field in ('name', 'password', 'user', 'uuid'):
                if values.get(field) is None:
                    values[field] = getattr(cls, field).get_value()
        return values


class ConfigGroup(orm.Entity):
    """A representation of a Config Group entity."""
    name = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/config_groups'
        server_modes = ('sat')


class ConfigTemplate(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Config Template entity."""
    audit_comment = orm.StringField(null=True)
    locked = orm.BooleanField(null=True)
    name = orm.StringField(required=True)
    operatingsystem = orm.OneToManyField('OperatingSystem', null=True)
    snippet = orm.BooleanField(null=True, required=True)
    # "Array of template combinations (hostgroup_id, environment_id)"
    template_combinations = orm.ListField(null=True)  # flake8:noqa pylint:disable=C0103
    template_kind = orm.OneToOneField('TemplateKind', null=True)
    template = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/config_templates'
        server_modes = ('sat')

    def _factory_data(self):
        """Customize the data provided to :class:`robottelo.factory.Factory`.

        Populate ``template_kind`` if:

        * this template is not a snippet, and
        * ``template_kind`` has no value.

        """
        values = super(ConfigTemplate, self)._factory_data()
        if 'snippet' in values.keys() and values['snippet'] is False:
            # A server is pre-populated with exactly eight template kinds. We
            # cannot just create a new template kind on the fly, which would be
            # preferred.
            values.setdefault(
                'template_kind_id',
                random.choice(
                    range(1, TemplateKind.Meta.NUM_CREATED_BY_DEFAULT + 1)
                )
            )
        return values


class ContentUpload(orm.Entity):
    """A representation of a Content Upload entity."""
    repository = orm.OneToOneField('Repository', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/repositories/:repository_id/'
                    'content_uploads')
        server_modes = ('sat')


class ContentViewVersion(orm.Entity):
    """A representation of a Content View Version non-entity."""

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/content_view_versions'
        server_modes = ('sat')

    def path(self, which=None):
        """Extend the default implementation of
        :meth:`robottelo.orm.Entity.path`.

        The format of the returned path depends on the value of ``which``:

        promote
            /content_view_versions/<id>/promote

        ``super`` is called otherwise.

        """
        if which == 'promote':
            return super(ContentViewVersion, self).path(
                which='self') + '/promote'
        return super(ContentViewVersion, self).path(which)

    def promote(self, environment_id, synchronous=True):
        """Helper for promoting an existing published content view.

        :param str environment_id: The environment Id to promote to.
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :return: A foreman task ID if an HTTP 202 (accepted) response is
            received, or None if any other response is received.

        """
        response = client.post(
            self.path('promote'),
            auth=get_server_credentials(),
            verify=False,
            data={u'environment_id': environment_id}
        )
        response.raise_for_status()

        # Return either a ForemanTask ID or None.
        if response.status_code is httplib.ACCEPTED:
            task_id = response.json()['id']
            if synchronous is True:
                ForemanTask(id=task_id).poll()
            return task_id
        return None


class ContentViewFilterRule(orm.Entity):
    """A representation of a Content View Filter Rule entity."""
    content_view_filter = orm.OneToOneField('ContentViewFilter', required=True)
    # package or package group: name
    name = orm.StringField()
    # package: version
    version = orm.StringField()
    # package: minimum version
    min_version = orm.StringField()
    # package: maximum version
    max_version = orm.StringField()
    # erratum: id
    errata = orm.OneToOneField('Errata')
    # erratum: start date (YYYY-MM-DD)
    start_date = orm.DateField(fmt='%Y-%m-%d')
    # erratum: end date (YYYY-MM-DD)
    end_date = orm.DateField(fmt='%Y-%m-%d')
    # erratum: types (enhancement, bugfix, security)
    types = orm.ListField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/content_view_filters/'
                    ':content_view_filter_id/rules')
        server_modes = ('sat')


class ContentViewFilter(orm.Entity):
    """A representation of a Content View Filter entity."""
    content_view = orm.OneToOneField('ContentView', required=True)
    name = orm.StringField(required=True)
    # type of filter (e.g. rpm, package_group, erratum)
    filter_type = orm.StringField(required=True)
    # Add all packages without Errata to the included/excluded list. (Package
    # Filter only)
    original_packages = orm.BooleanField()
    # specifies if content should be included or excluded, default: false
    inclusion = orm.BooleanField()
    repositories = orm.OneToManyField('Repository')

    class Meta(object):
        """Non-field information about this entity."""
        api_names = (('filter_type', 'type'),)
        api_path = 'katello/api/v2/content_view_filters'
        # Alternative path
        #
        # '/katello/api/v2/content_views/:content_view_id/filters',
        server_modes = ('sat')


class ContentViewPuppetModule(orm.Entity):
    """A representation of a Content View Puppet Module entity."""
    content_view = orm.OneToOneField('ContentView', required=True)
    name = orm.StringField()
    author = orm.StringField()
    uuid = orm.StringField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/content_views/:content_view_id/'
                    'content_view_puppet_modules')
        server_modes = ('sat')


class ContentView(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Content View entity."""
    organization = orm.OneToOneField('Organization', required=True)
    name = orm.StringField(required=True)
    label = orm.StringField()
    composite = orm.BooleanField()
    description = orm.StringField()
    repository = orm.OneToManyField('Repository')
    # List of component content view version ids for composite views
    component = orm.OneToManyField('ContentView')

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/content_views'
        # Alternative paths
        #
        # '/katello/api/v2/organizations/:organization_id/content_views',
        server_modes = ('sat')

    def path(self, which=None):
        """Extend the default implementation of
        :meth:`robottelo.orm.Entity.path`.

        The format of the returned path depends on the value of ``which``:

        content_view_puppet_modules
            /content_views/<id>/content_view_puppet_modules
        content_view_versions
            /content_views/<id>/content_view_versions
        publish
            /content_views/<id>/publish
        available_puppet_module_names
            /content_views/<id>/available_puppet_module_names

        ``super`` is called otherwise.

        """
        if which in (
                'content_view_puppet_modules', 'content_view_versions',
                'publish', 'available_puppet_module_names'):
            return '{0}/{1}'.format(
                super(ContentView, self).path(which='self'),
                which
            )
        return super(ContentView, self).path(which)

    def publish(self, synchronous=True):
        """Helper for publishing an existing content view.

        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :return: A foreman task ID if an HTTP 202 (accepted) response is
            received, or None if any other response is received.

        """
        response = client.post(
            self.path('publish'),
            auth=get_server_credentials(),
            verify=False,
            data={u'id': self.id}
        )
        response.raise_for_status()

        # Return either a ForemanTask ID or None.
        if response.status_code is httplib.ACCEPTED:
            task_id = response.json()['id']
            if synchronous is True:
                ForemanTask(id=task_id).poll()
            return task_id
        return None


class CustomInfo(orm.Entity):
    """A representation of a Custom Info entity."""
    # name of the resource
    informable_type = orm.StringField(required=True)
    # resource identifier
    # FIXME figure out related resource
    # informable = orm.OneToOneField(required=True)
    keyname = orm.StringField(required=True)
    value = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/custom_info/:informable_type/'
                    ':informable_id')
        server_modes = ('sat')


class Domain(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Domain entity."""
    domain_parameters_attributes = orm.ListField(null=True)
    fullname = orm.StringField(null=True)
    name = orm.StringField(required=True)
    # DNS Proxy to use within this domain
    # FIXME figure out related resource
    # dns = orm.OneToOneField(null=True)

    def _factory_data(self):
        """Customize the data provided to :class:`robottelo.factory.Factory`.

        By default, :meth:`robottelo.orm.URLField.get_value` does not return
        especially unique values. This is problematic, as all domain names must
        be unique.

        """
        if self.name is None:
            self.name = gen_alphanumeric().lower()
        return super(Domain, self)._factory_data()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/domains'
        server_modes = ('sat')


class Environment(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Environment entity."""
    name = orm.StringField(
        required=True,
        str_type=('alpha', 'numeric', 'alphanumeric'),
    )

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/environments'
        server_modes = ('sat')


class Errata(orm.Entity):
    """A representation of an Errata entity."""
    # You cannot create an errata. Instead, errata are a read-only entity.

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/errata'
        server_modes = ('sat')


class Filter(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Filter entity."""
    role = orm.OneToOneField('Role', required=True)
    search = orm.StringField(null=True)
    permission = orm.OneToManyField('Permission', null=True)
    organization = orm.OneToManyField('Organization', null=True)
    location = orm.OneToManyField('Location', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/filters'
        server_modes = ('sat')


class ForemanTask(orm.Entity, orm.EntityReadMixin):
    """A representation of a Foreman task."""

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'foreman_tasks/api/tasks'
        server_modes = ('sat')

    def path(self, which=None):
        """Override the default implementation of
        :meth:`robottelo.orm.Entity.path`.

        The format of the returned path depends on the value of ``which``:

        bulk_search
            /foreman_tasks/api/tasks/bulk_search

        ``super(which='self')`` is called otherwise. There is no path available
        for fetching all tasks.

        """
        if which == 'bulk_search':
            return '{0}/bulk_search'.format(
                super(ForemanTask, self).path(which='base')
            )
        return super(ForemanTask, self).path(which='self')

    def poll(self, poll_rate=5, timeout=120, auth=None):
        """Return the status of a task or timeout.

        There are several API calls that trigger asynchronous tasks, such as
        synchronizing a repository, or publishing or promoting a content view.
        It is possible to check on the status of a task if you know its UUID.
        This method polls a task once every ``poll_rate`` seconds and, upon
        task completion, returns information about that task.

        :param int poll_rate: Delay between the end of one task check-up and
            the start of the next check-up.
        :param int timeout: Maximum number of seconds to wait until timing out.
        :param tuple auth: A ``(username, password)`` tuple used when accessing
            the API. If ``None``, the credentials provided by
            :func:`robottelo.common.helpers.get_server_credentials` are used.
        :returns: Information about the asynchronous task.
        :rtype: dict
        :raises robottelo.orm.TaskTimeout: If the task is not finished before
            the timeout is exceeded.
        :raises: ``requests.exceptions.HTTPError`` If the API returns a message
            with an HTTP 4XX or 5XX status code.

        """
        # (protected-access) pylint:disable=W0212
        # See docstring for orm._poll_task for an explanation.
        return orm._poll_task(self.id, poll_rate, timeout, auth)


def _gpgkey_content():
    """Return default content for a GPG key.

    :returns: The contents of a GPG key.
    :rtype: str

    """
    with open(get_data_file(VALID_GPG_KEY_FILE)) as handle:
        return handle.read()


class GPGKey(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a GPG Key entity."""
    organization = orm.OneToOneField('Organization', required=True)
    location = orm.OneToOneField('Location', null=True)
    # identifier of the gpg key
    # validator: string from 2 to 128 characters containting only alphanumeric
    # characters, space, '_', '-' with no leading or trailing space.
    name = orm.StringField(required=True)
    # public key block in DER encoding
    content = orm.StringField(required=True, default=_gpgkey_content())

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/gpg_keys'
        server_modes = ('sat')


class HostClasses(orm.Entity):
    """A representation of a Host Class entity."""
    host = orm.OneToOneField('Host', required=True)
    puppetclass = orm.OneToOneField('PuppetClass', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/hosts/:host_id/puppetclass_ids'
        server_modes = ('sat')


class HostCollectionErrata(orm.Entity):
    """A representation of a Host Collection Errata entity."""
    errata = orm.OneToManyField('Errata', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/organizations/:organization_id/'
                    'host_collections/:host_collection_id/errata')
        server_modes = ('sat')


class HostCollectionPackage(orm.Entity):
    """A representation of a Host Collection Package entity."""
    packages = orm.ListField()
    groups = orm.ListField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/organizations/:organization_id/'
                    'host_collections/:host_collection_id/packages')
        server_modes = ('sat')


class HostCollection(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Host Collection entity."""
    description = orm.StringField()
    max_content_hosts = orm.IntegerField()
    name = orm.StringField(required=True)
    organization = orm.OneToOneField('Organization', required=True)
    system = orm.OneToManyField('System')

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/host_collections'
        # Alternative paths.
        #
        # '/katello/api/v2/organizations/:organization_id/host_collections'
        server_modes = ('sat', 'sam')


class HostGroupClasses(orm.Entity):
    """A representation of a Host Group Classes entity."""
    hostgroup = orm.OneToOneField('HostGroup', required=True)
    puppetclass = orm.OneToOneField('PuppetClass', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/hostgroups/:hostgroup_id/puppetclass_ids'
        server_modes = ('sat')


class HostGroup(orm.Entity, factory.EntityFactoryMixin):
    """A representation of a Host Group entity."""
    name = orm.StringField(required=True)
    parent = orm.OneToOneField('HostGroup', null=True)
    environment = orm.OneToOneField('Environment', null=True)
    operatingsystem = orm.OneToOneField('OperatingSystem', null=True)
    architecture = orm.OneToOneField('Architecture', null=True)
    medium = orm.OneToOneField('Media', null=True)
    ptable = orm.OneToOneField('PartitionTable', null=True)
    # FIXME figure out related resource
    # puppet_ca_proxy = orm.OneToOneField(null=True)
    subnet = orm.OneToOneField('Subnet', null=True)
    domain = orm.OneToOneField('Domain', null=True)
    realm = orm.OneToOneField('Realm', null=True)
    # FIXME figure out related resource
    # puppet_proxy = orm.OneToOneField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/hostgroups'
        server_modes = ('sat')


class Host(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Host entity."""
    architecture = orm.OneToOneField('Architecture', null=True, required=True)
    build_ = orm.BooleanField(null=True)
    capabilities = orm.StringField(null=True)
    compute_profile = orm.OneToOneField('ComputeProfile', null=True)
    compute_resource = orm.OneToOneField('ComputeResource', null=True)
    domain = orm.OneToOneField('Domain', null=True, required=True)
    enabled = orm.BooleanField(null=True)
    environment = orm.OneToOneField('Environment', null=True, required=True)
    hostgroup = orm.OneToOneField('HostGroup', null=True)
    host_parameters_attributes = orm.ListField(null=True)
    image = orm.OneToOneField('Image', null=True)
    ip = orm.StringField(null=True)  # (invalid-name) pylint:disable=C0103
    location = orm.OneToOneField('Location', required=True)
    mac = orm.MACAddressField(null=True, required=True)
    managed = orm.BooleanField(null=True)
    medium = orm.OneToOneField('Media', null=True)
    model = orm.OneToOneField('Model', null=True)
    name = orm.StringField(required=True, str_type=('alpha',))
    operatingsystem = orm.OneToOneField(
        'OperatingSystem',
        null=True,
        required=True
    )
    organization = orm.OneToOneField('Organization', required=True)
    owner = orm.OneToOneField('User', null=True)
    provision_method = orm.StringField(null=True)
    ptable = orm.OneToOneField('PartitionTable', null=True)
    puppet_classes = orm.OneToManyField('PuppetClass', null=True)
    puppet_proxy = orm.OneToOneField('SmartProxy', null=True, required=True)
    realm = orm.OneToOneField('Realm', null=True)
    root_pass = orm.StringField(len=(8, 30), required=True)
    sp_subnet = orm.OneToOneField('Subnet', null=True)
    subnet = orm.OneToOneField('Subnet', null=True)

    # FIXME figure out these related resources
    # progress_report = orm.OneToOneField(null=True)
    # puppet_ca_proxy = orm.OneToOneField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_names = (('build_', 'build'),)
        api_path = 'api/v2/hosts'
        server_modes = ('sat')

    def _factory_data(self):
        """Extend :meth:`robottelo.factory.Factory._factory_data`.

        A host's dependency graph must, in part, look like this::

                 .-> medium --------.
                 |-> architecture <-V--.
            host --> operating system -|
                 |-> partition table <-'
                 `-> smart proxy

        This is complicated by the fact that the user might provide values for
        any number of fields, it is impossible to create a bogus smart proxy,
        some links are optional and the links are a combination of one-to-one
        and one-to-many. This method will create a dependent architecture,
        operating system, partition table and medium **only if all four fields
        are unset.**

        """
        if (self.operatingsystem is None and
                self.architecture is None and
                self.ptable is None and
                self.medium is None):
            self.architecture = Architecture().create()['id']
            self.ptable = PartitionTable().create()['id']
            self.operatingsystem = OperatingSystem(
                architecture=[self.architecture],
                ptable=[self.ptable],
            ).create()['id']
            self.medium = Media(
                operatingsystem=[self.operatingsystem]
            ).create()['id']
        if self.puppet_proxy is None:
            response = client.get(
                SmartProxy().path(),
                auth=get_server_credentials(),
                verify=False,
            )
            response.raise_for_status()
            self.puppet_proxy = response.json()['results'][0]['id']
        return super(Host, self)._factory_data()


class Image(orm.Entity):
    """A representation of a Image entity."""
    compute_resource = orm.OneToOneField('ComputeResource', required=True)
    name = orm.StringField(required=True)
    username = orm.StringField(required=True)
    uuid = orm.StringField(required=True)
    architecture = orm.OneToOneField('Architecture', required=True)
    operatingsystem = orm.OneToOneField('OperatingSystem', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/compute_resources/:compute_resource_id/images'
        server_modes = ('sat')


class Interface(orm.Entity):
    """A representation of a Interface entity."""
    host = orm.OneToOneField('Host', required=True)
    mac = orm.MACAddressField(required=True)
    ip = orm.IPAddressField(required=True)  # pylint:disable=C0103
    # Interface type, i.e: Nic::BMC
    interface_type = orm.StringField(required=True)
    name = orm.StringField(required=True)
    subnet = orm.OneToOneField('Subnet', null=True)
    domain = orm.OneToOneField('Domain', null=True)
    username = orm.StringField(null=True)
    password = orm.StringField(null=True)
    # Interface provider, i.e: IPMI
    provider = orm.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_names = (('interface_type', 'type'),)
        api_path = 'api/v2/hosts/:host_id/interfaces'
        server_modes = ('sat')


class LifecycleEnvironment(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Lifecycle Environment entity."""
    organization = orm.OneToOneField('Organization', required=True)
    name = orm.StringField(required=True)
    description = orm.StringField()
    # A prior environment in a tree of lifecycle environments. The root of the
    # tree has name of 'Library' and no value in this field.
    # FIXME: This field is not required. Remove `required` and update other
    # methods to deal with the change.
    prior = orm.OneToOneField('LifecycleEnvironment', required=True)

    def _factory_data(self):
        """Extend the default implementation of
        :meth:`robottelo.factory.EntityFactoryMixin._factory_data`.

        Since a ``LifecycleEnvironment`` can be associated to another instance
        of a ``LifecycleEnvironment`` via the ``prior`` field, the expected
        foreignkey is not ``prior_id`` as expected, but ``prior``. Therefore, we
        must update the entity's fields and make sure that we have a ``prior``
        attribute before any further actions can be performed.

        """
        lc_attrs = super(LifecycleEnvironment, self)._factory_data()
        # Add ``prior`` back into the fields
        lc_attrs['prior'] = lc_attrs.pop('prior_id')
        return lc_attrs

    def build(self, auth=None):
        """Extend the implementation of :meth:`robottelo.factory.Factory.build`.

        When a new lifecycle environment is created, it must either:

        * Reference some other lifecycle environment via the "prior" field.
        * Have a name of "Library". Note that within a given organization, there
          can only be a single lifecycle environment with a name of "Library".

        This method does the following:

        1. If this entity does not yet point to an organization (i.e. if
           ``self.organization is None``), an organization is created.
        2. If this entity does not yet point to another lifecycle entity (i.e.
           if ``self.prior is None``), the "Library" lifecycle environment for
           this lifecycle environment's organization is found and used.

        """
        if self.organization is None:
            self.organization = Organization().create(auth=auth)['id']
        if self.prior is None:
            query_results = client.get(
                self.path(),
                auth=get_server_credentials(),
                verify=False,
                data={
                    u'name': 'Library',
                    u'organization_id': self.organization,
                }
            ).json()['results']
            if len(query_results) != 1:
                raise APIResponseError(
                    'Could not find the "Library" lifecycle environment for '
                    'organization {0}. Search returned {1} results.'
                    ''.format(self.organization, len(query_results))
                )
            self.prior = query_results[0]['id']
        return super(LifecycleEnvironment, self).build(auth)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/environments'
        server_modes = ('sat')


class Location(orm.Entity, factory.EntityFactoryMixin):
    """A representation of a Location entity."""
    name = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/locations'
        server_modes = ('sat')


class Media(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Media entity."""
    media_path = orm.URLField(required=True)
    name = orm.StringField(required=True)
    operatingsystem = orm.OneToManyField('OperatingSystem', null=True)
    os_family = orm.StringField(choices=(
        'AIX', 'Archlinux', 'Debian', 'Freebsd', 'Gentoo', 'Junos', 'Redhat',
        'Solaris', 'Suse', 'Windows',
    ), null=True)

    def _factory_data(self):
        """Customize the data provided to :class:`robottelo.factory.Factory`.

        By default, :meth:`robottelo.orm.URLField.get_value` does not return
        especially unique values. This is problematic, as all media must have a
        unique path.

        """
        if self.media_path is None:
            self.media_path = gen_url(
                subdomain=gen_alpha()
            )
        return super(Media, self)._factory_data()

    # NOTE: See BZ 1151220
    def create(self, auth=None, data=None):
        """Extend the implementation of
        :meth:`robottelo.factory.Factory.create`.

        Clients must submit a nested hash of attributes when creating a
        media. For example, this will not work correctly::

            {'name': 'foo', 'operatingsystem_ids': [1, 2, 3]}

        However, this will work correctly::

            {'medium': {'name': 'foo', 'operatingsystem_ids': [1, 2, 3]}}

        """
        if data is None:
            data = {u'medium': self.build(auth=auth)}
        return super(Media, self).create(auth, data)

    # NOTE: See BZ 1151240
    def read(self, auth=None, entity=None, attrs=None):
        """Override the default implementation of
        :meth:`robottelo.orm.EntityReadMixin.read`.

        A media points to zero or more operating systems. Unfortunately, the
        API communicates the list of pointed-to operating systems as a list of
        hashes named "operatingsystems"::

            {
                u'name': u'foo',
                u'operatingsystems': [
                    {u'id': 1, u'name': u'rhel65'},
                    {u'id': 2, u'name': u'rhel7'},
                ]
            }

        This is incorrect behaviour. The API _should_ return a list of IDs
        named "operatingsystem_ids"::

            {u'name': u'foo', u'operatingsystem_ids': [1, 2]}

        """
        if attrs is None:
            attrs = self.read_json(auth)
        attrs['operatingsystem_ids'] = [
            operatingsystem['id']
            for operatingsystem
            in attrs.pop('operatingsystems')
        ]
        return super(Media, self).read(auth, entity, attrs)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/media'
        api_names = (('media_path', 'path'),)
        server_modes = ('sat')


class Model(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Model entity."""
    name = orm.StringField(required=True)
    info = orm.StringField(null=True)
    vendor_class = orm.StringField(null=True)
    hardware_model = orm.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/models'
        server_modes = ('sat')


class OperatingSystem(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Operating System entity.

    ``major`` is listed as a string field in the API docs, but only numeric
    values are accepted, and they may be no longer than 5 digits long. Also see
    bugzilla bug #1122261.

    The following fields are valid despite not being listed in the API docs:

    * architecture
    * medium
    * ptable

    """
    architecture = orm.OneToManyField('Architecture')
    description = orm.StringField(null=True)
    family = orm.StringField(null=True, choices=OPERATING_SYSTEMS)
    major = orm.StringField(required=True, str_type=('numeric',), len=(1, 5))
    media = orm.OneToManyField('Media')
    minor = orm.StringField(null=True)
    name = orm.StringField(required=True)
    ptable = orm.OneToManyField('PartitionTable')
    release_name = orm.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/operatingsystems'
        api_names = (
            ('media_ids', 'media'),
            ('ptable_ids', 'ptables'),
            ('architecture_ids', 'architectures'),
        )
        server_modes = ('sat')

    # NOTE: See BZ 1151220
    def create(self, auth=None, data=None):
        """Extend the implementation of
        :meth:`robottelo.factory.Factory.create`.

        Clients must submit a nested hash of attributes when creating an
        operating system that points to an architecture or partition table.
        For example, this will not work correctly::

            {'name': 'foo', 'ptable_ids': [1, 2], 'architecture_ids': [2, 3]}

        However, this will work correctly::

            {'operatingsystem': {
                'name': 'foo', 'ptable_ids': [1, 2], 'architecture_ids': [2, 3]
            }}

        """
        if data is None:
            data = {u'operatingsystem': self.build(auth=auth)}
        return super(OperatingSystem, self).create(auth, data)


class OperatingSystemParameter(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a parameter for an operating system."""
    name = orm.StringField(required=True)
    value = orm.StringField(required=True)

    def __init__(self, os_id, **kwargs):
        """Record ``os_id`` and set ``self.Meta.api_path``."""
        self.os_id = os_id
        self.Meta.api_path = '{0}/parameters'.format(
            OperatingSystem(id=os_id).path()
        )
        super(OperatingSystemParameter, self).__init__(**kwargs)

    def read(self, auth=None, entity=None, attrs=None):
        """Override the default implementation of
        :meth:`robottelo.orm.EntityReadMixin.read`.

        """
        # Passing `entity=self` also succeeds. However, the attributes of the
        # object passed in will be clobbered. Passing in a new object allows
        # this one to avoid changing state. The default implementation of
        # `read` follows the same principle.
        return super(OperatingSystemParameter, self).read(
            auth=auth,
            entity=OperatingSystemParameter(self.os_id),
            attrs=attrs
        )


class OrganizationDefaultInfo(orm.Entity):
    """A representation of a Organization Default Info entity."""
    # name of the resource
    informable_type = orm.StringField(required=True)
    # resource identifier
    # FIXME figure out related resource
    # informable = orm.OneToOneField(required=True)
    keyname = orm.StringField(required=True)
    name = orm.StringField(required=True)
    info = orm.StringField()
    vendor_class = orm.StringField()
    hardware_model = orm.StringField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('katello/api/v2/organizations/:organization_id/'
                    'default_info/:informable_type')
        server_modes = ('sat', 'sam')


class Organization(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of an Organization entity."""
    name = orm.StringField(required=True)
    label = orm.StringField(str_type=('alpha',))
    description = orm.StringField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/organizations'
        server_modes = ('sat', 'sam')

    def path(self, which=None):
        """Extend the default implementation of
        :meth:`robottelo.orm.Entity.path`.

        The format of the returned path depends on the value of ``which``:

        subscriptions/upload
            /organizations/<id>/subscriptions/upload
        subscriptions/delete_manifest
            /organizations/<id>/subscriptions/delete_manifest
        subscriptions/refresh_manifest
            /organizations/<id>/subscriptions/refresh_manifest
        sync_plans
            /organizations/<id>/sync_plans
        products
            /organizations/<id>/products
        subscriptions
            /organizations/<id>/subscriptions

        Otherwise, call ``super``.

        """
        if which in (
                'products',
                'subscriptions/delete_manifest',
                'subscriptions/refresh_manifest',
                'subscriptions/upload',
                'sync_plans',
                'subscriptions',
        ):
            return '{0}/{1}'.format(
                super(Organization, self).path(which='self'),
                which
            )
        return super(Organization, self).path(which)

    def subscriptions(self):
        """List the organization's subscriptions.

        :returns: A list of available subscriptions.
        :rtype: list
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.

        """
        response = client.get(
            self.path('subscriptions'),
            auth=get_server_credentials(),
            verify=False,
        )
        response.raise_for_status()
        return response.json()['results']

    def upload_manifest(self, path, repository_url=None,
                        synchronous=True):
        """Helper method that uploads a subscription manifest file

        :param str path: Local path of the manifest file
        :param str repository_url: Optional repository URL
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :returns: The ID of a :class:`robottelo.entities.ForemanTask` if an HTTP
            202 response was received. ``None`` otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: :class:`robottelo.orm.TaskTimeout` if an HTTP 202 response is
            received, ``synchronous is True`` and polling times out.

        """
        data = None
        if repository_url is not None:
            data = {u'repository_url': repository_url}

        with open(path, 'rb') as manifest:
            response = client.post(
                self.path('subscriptions/upload'),
                auth=get_server_credentials(),
                verify=False,
                data=data,
                files={'content': manifest},
            )
        response.raise_for_status()

        # Return either a ForemanTask ID or None.
        if response.status_code is httplib.ACCEPTED:
            task_id = response.json()['id']
            if synchronous is True:
                ForemanTask(id=task_id).poll()
            return task_id
        return None

    def delete_manifest(self, synchronous=True):
        """Helper method that deletes an organization's manifest

        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :returns: The ID of a :class:`robottelo.entities.ForemanTask` if an HTTP
            202 response was received. ``None`` otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: :class:`robottelo.orm.TaskTimeout` if an HTTP 202 response is
            received, ``synchronous is True`` and polling times out.

        """
        response = client.post(
            self.path('subscriptions/delete_manifest'),
            auth=get_server_credentials(),
            verify=False,
        )
        response.raise_for_status()

        # Return either a ForemanTask ID or None.
        if response.status_code is httplib.ACCEPTED:
            task_id = response.json()['id']
            if synchronous is True:
                ForemanTask(id=task_id).poll()
            return task_id
        return None

    def refresh_manifest(self, synchronous=True):
        """Helper method that refreshes an organization's manifest

        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :returns: The ID of a :class:`robottelo.entities.ForemanTask` if an HTTP
            202 response was received. ``None`` otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: :class:`robottelo.orm.TaskTimeout` if an HTTP 202 response is
            received, ``synchronous is True`` and polling times out.

        """
        response = client.put(
            self.path('subscriptions/refresh_manifest'),
            auth=get_server_credentials(),
            verify=False,
        )
        response.raise_for_status()

        # Return either a ForemanTask ID or None.
        if response.status_code is httplib.ACCEPTED:
            task_id = response.json()['id']
            if synchronous is True:
                ForemanTask(id=task_id).poll()
            return task_id
        return None

    def sync_plan(self, name, interval):
        """Helper for creating a sync_plan.

        :returns: The server's response, with all JSON decoded.
        :rtype: dict
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """

        sync_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        response = client.post(
            self.path('sync_plans'),
            auth=get_server_credentials(),
            verify=False,
            data={u'name': name,
                  u'interval': interval,
                  u'sync_date': sync_date},
        )
        response.raise_for_status()
        return response.json()

    def list_rhproducts(self, per_page=None):
        """Lists all the RedHat Products after the importing of a manifest.

        :param int per_page: The no.of results to be shown per page.

        """
        response = client.get(
            self.path('products'),
            auth=get_server_credentials(),
            verify=False,
            data={u'per_page': per_page},
        )
        response.raise_for_status()
        return response.json()['results']

    def fetch_rhproduct_id(self, name):
        """Fetches the RedHat Product Id for a given Product name.

        To be used for the Products created when manifest is imported.
        RedHat Product Id could vary depending upon other custom products.
        So, we use the product name to fetch the RH Product Id.

        :param str name: The RedHat product's name who's ID is to be fetched.
        :returns: The RedHat Product Id is returned.

        """
        response = client.get(
            self.path('products'),
            auth=get_server_credentials(),
            verify=False,
            data={u'search': 'name={}'.format(escape_search(name))},
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                "The length of the results is:", len(results))
        else:
            return results[0]['id']


class OSDefaultTemplate(orm.Entity):
    """A representation of a OS Default Template entity."""
    operatingsystem = orm.OneToOneField('OperatingSystem')
    template_kind = orm.OneToOneField('TemplateKind', null=True)
    config_template = orm.OneToOneField('ConfigTemplate', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('api/v2/operatingsystems/:operatingsystem_id/'
                    'os_default_templates')
        server_modes = ('sat')


class OverrideValue(orm.Entity):
    """A representation of a Override Value entity."""
    smart_variable = orm.OneToOneField('SmartVariable')
    match = orm.StringField(null=True)
    value = orm.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        # FIXME: This is tricky. Overriding path() may be a solution.
        api_path = (
            # Create an override value for a specific smart_variable
            '/api/v2/smart_variables/:smart_variable_id/override_values',
            # Create an override value for a specific smart class parameter
            '/api/v2/smart_class_parameters/:smart_class_parameter_id/'
            'override_values',
        )
        server_modes = ('sat')


class Permission(orm.Entity, orm.EntityReadMixin):
    """A representation of a Permission entity."""
    name = orm.StringField(required=True)
    resource_type = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/permissions'
        server_modes = ('sat', 'sam')

    def search(self, per_page=10000):
        """Searches for permissions using the values for instance name and
        resource_type

        Usage::

            result = Permission(resource_type='Architecture').search()
            result = Permission(name='create_architectures').search()

        If you search by using both name and resource_type then the default
        server behavior is to search by resource_type.

        :param int per_page: number of results per page to return
        :returns: A list with the found results
        :rtype: list

        """
        search_terms = {u'per_page': per_page}
        if self.name is not None:
            search_terms[u'name'] = self.name
        if self.resource_type is not None:
            search_terms[u'resource_type'] = self.resource_type

        response = client.get(
            self.path('base'),
            auth=get_server_credentials(),
            verify=False,
            data=search_terms
        )
        response.raise_for_status()
        return response.json()['results']


class Ping(orm.Entity):
    """A representation of a Ping entity."""

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/ping'
        server_modes = ('sat', 'sam')


class Product(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Product entity."""
    organization = orm.OneToOneField('Organization', required=True)
    location = orm.OneToOneField('Location', null=True)
    description = orm.StringField()
    gpg_key = orm.OneToOneField('GPGKey')
    sync_plan = orm.OneToOneField('SyncPlan', null=True)
    name = orm.StringField(required=True)
    label = orm.StringField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/products'
        server_modes = ('sat', 'sam')

    def path(self, which=None):
        """Extend the default implementation of
        :meth:`robottelo.orm.Entity.path`.

        The format of the returned path depends on the value of ``which``:

        repository_sets
            /products/<product_id>/repository_sets
        repository_sets/<id>/enable
            /products/<product_id>/repository_sets/<id>/enable
        repository_sets/<id>/disable
            /products/<product_id>/repository_sets/<id>/disable

        ``super`` is called otherwise.

        """
        if which is not None and which.startswith("repository_sets"):
            return '{0}/{1}'.format(
                super(Product, self).path(which='self'),
                which,
            )
        return super(Product, self).path(which)

    def list_repositorysets(self, per_page=None):
        """Lists all the RepositorySets in a Product.

        :param int per_page: The no.of results to be shown per page.

        """
        response = client.get(
            self.path('repository_sets'),
            auth=get_server_credentials(),
            verify=False,
            data={u'per_page': per_page}
        )
        response.raise_for_status()
        return response.json()['results']

    def fetch_rhproduct_id(self, name, org_id):
        """Fetches the RedHat Product Id for a given Product name.

        To be used for the Products created when manifest is imported.
        RedHat Product Id could vary depending upon other custom products.
        So, we use the product name to fetch the RedHat Product Id.

        :param str org_id: The Organization Id.
        :param str name: The RedHat product's name who's ID is to be fetched.
        :returns: The RedHat Product Id is returned.

        """
        response = client.get(
            self.path(which='base'),
            auth=get_server_credentials(),
            verify=False,
            data={u'search': 'name={}'.format(escape_search(name)),
                  u'organization_id': org_id},
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                "The length of the results is:", len(results))
        return results[0]['id']

    def fetch_reposet_id(self, name):
        """Fetches the RepositorySet Id for a given name.

        RedHat Products do not directly contain Repositories.
        Product first contains many RepositorySets and each
        RepositorySet contains many Repositories.
        RepositorySet Id could vary. So, we use the reposet name
        to fetch the RepositorySet Id.

        :param str name: The RepositorySet's name.
        :returns: The RepositorySet's Id is returned.

        """
        response = client.get(
            self.path('repository_sets'),
            auth=get_server_credentials(),
            verify=False,
            data={u'name': name},
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                "The length of the results is:", len(results))
        return results[0]['id']

    def enable_rhrepo(self, base_arch,
                      release_ver, reposet_id, synchronous=True):
        """Enables the RedHat Repository

        RedHat Repos needs to be enabled first, so that we can sync it.

        :param str reposet_id: The RepositorySet Id.
        :param str base_arch: The architecture type of the repo to enable.
        :param str release_ver: The release version type of the repo to enable.
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :returns: A foreman task ID if an HTTP 202 (accepted) response is
            received, or None if any other response is received.

        """
        response = client.put(
            self.path('repository_sets/{0}/enable'.format(reposet_id)),
            auth=get_server_credentials(),
            verify=False,
            data={u'basearch': base_arch,
                  u'releasever': release_ver},
        )
        response.raise_for_status()

        # Return either a ForemanTask ID or None.
        if response.status_code is httplib.ACCEPTED:
            task_id = response.json()['id']
            if synchronous is True:
                ForemanTask(id=task_id).poll()
            return task_id
        return None

    def disable_rhrepo(self, base_arch,
                       release_ver, reposet_id, synchronous=True):
        """Disables the RedHat Repository

        :param str reposet_id: The RepositorySet Id.
        :param str base_arch: The architecture type of the repo to disable.
        :param str release_ver: The release version type of the repo to
            disable.
        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :returns: A foreman task ID if an HTTP 202 (accepted) response is
            received, or None if any other response is received.

        """
        response = client.put(
            self.path('repository_sets/{0}/disable'.format(reposet_id)),
            auth=get_server_credentials(),
            verify=False,
            data={u'basearch': base_arch,
                  u'releasever': release_ver},
        )
        response.raise_for_status()

        # Return either a ForemanTask ID or None.
        if response.status_code is httplib.ACCEPTED:
            task_id = response.json()['id']
            if synchronous is True:
                ForemanTask(id=task_id).poll()
            return task_id
        return None


class PartitionTable(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Partition Table entity."""
    name = orm.StringField(required=True)
    layout = orm.StringField(required=True)
    os_family = orm.StringField(null=True, choices=OPERATING_SYSTEMS)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/ptables'
        server_modes = ('sat')


class PuppetClass(orm.Entity):
    """A representation of a Puppet Class entity."""
    name = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/puppetclasses'
        server_modes = ('sat')


class Realm(orm.Entity):
    """A representation of a Realm entity."""
    # The realm name, e.g. EXAMPLE.COM
    name = orm.StringField(required=True)
    # Proxy to use for this realm
    # FIXME figure out related resource
    # realm_proxy = orm.OneToOneField(null=True)
    # Realm type, e.g. Red Hat Identity Management or Active Directory
    realm_type = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/realms'
        server_modes = ('sat')


class Report(orm.Entity):
    """A representation of a Report entity."""
    # Hostname or certname
    host = orm.StringField(required=True)
    # UTC time of report
    reported_at = orm.DateTimeField(required=True)
    # Optional array of log hashes
    logs = orm.ListField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/reports'
        server_modes = ('sat')


class Repository(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Repository entity."""
    checksum_type = orm.StringField(choices=('sha1', 'sha256'))
    content_type = orm.StringField(
        choices=('puppet', 'yum', 'file'),
        default='yum',
        required=True,
    )
    gpg_key = orm.OneToOneField('GPGKey')
    label = orm.StringField()
    name = orm.StringField(required=True)
    product = orm.OneToOneField('Product', required=True)
    unprotected = orm.BooleanField()
    url = orm.URLField(required=True, default=FAKE_1_YUM_REPO)

    def path(self, which=None):
        """Extend the default implementation of
        :meth:`robottelo.orm.Entity.path`.

        The format of the returned path depends on the value of ``which``:

        sync
            /repositories/<id>/sync
        upload_content
            /repositories/<id>/upload_content

        ``super`` is called otherwise.

        """
        if which in ('sync', 'upload_content'):
            return '{0}/{1}'.format(
                super(Repository, self).path(which='self'),
                which
            )
        return super(Repository, self).path(which)

    # NOTE: See BZ 1151240
    def read(self, auth=None, entity=None, attrs=None):
        """Override the default implementation of
        :meth:`robottelo.orm.EntityReadMixin.read`.

        """
        if attrs is None:
            attrs = self.read_json(auth)
        attrs['product_id'] = attrs.pop('product')['id']
        return super(Repository, self).read(auth, entity, attrs)

    def sync(self, synchronous=True):
        """Helper for syncing an existing repository.

        :param bool synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :returns: A foreman task ID if an HTTP 202 (accepted) response is
            received, or None if any other response is received.

        """
        response = client.post(
            self.path('sync'),
            auth=get_server_credentials(),
            verify=False,
        )
        response.raise_for_status()

        # Return either a ForemanTask ID or None.
        if response.status_code is httplib.ACCEPTED:
            task_id = response.json()['id']
            if synchronous is True:
                ForemanTask(id=task_id).poll()
            return task_id
        return None

    def fetch_repoid(self, org_id, name):
        """Fetch the repository Id.

        This is required for RedHat Repositories, as products, reposets
        and repositories get automatically populated upon the manifest import.

        :param str org_id: The org Id for which repository listing is required.
        :param str name: The repository name who's Id has to be searched.
        :return: Returns the repository Id.
        :rtype: str
        :raises: ``APIResponseError`` If the API does not return any results.

        """
        response = client.get(
            self.path(which=None),
            auth=get_server_credentials(),
            verify=False,
            data={u'organization_id': org_id,
                  u'search': 'name={}'.format(escape_search(name))}
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                "The length of the results is:", len(results))
        return results[0]['id']

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/repositories'
        server_modes = ('sat')


class RoleLDAPGroups(orm.Entity):
    """A representation of a Role LDAP Groups entity."""
    name = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/roles/:role_id/ldap_groups'
        server_modes = ('sat', 'sam')


class Role(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Role entity."""
    # FIXME: UTF-8 characters should be acceptable for `name`. See BZ 1129785
    name = orm.StringField(
        required=True,
        str_type=('alphanumeric',),
        len=(2, 30),  # min length is 2 and max length is arbitrary
    )

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/roles'
        server_modes = ('sat', 'sam')


class SmartProxy(orm.Entity):
    """A representation of a Smart Proxy entity."""
    name = orm.StringField(required=True)
    url = orm.URLField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/smart_proxies'
        server_modes = ('sat')


class SmartVariable(orm.Entity):
    """A representation of a Smart Variable entity."""
    variable = orm.StringField(required=True)
    puppetclass = orm.OneToOneField('PuppetClass', null=True)
    default_value = orm.StringField(null=True)
    override_value_order = orm.StringField(null=True)
    description = orm.StringField(null=True)
    validator_type = orm.StringField(null=True)
    validator_rule = orm.StringField(null=True)
    variable_type = orm.StringField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/smart_variables'
        server_modes = ('sat')


class Status(orm.Entity):
    """A representation of a Status entity."""

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/status'
        server_modes = ('sat')


class Subnet(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a Subnet entity."""
    dns_primary = orm.IPAddressField(null=True)
    dns_secondary = orm.IPAddressField(null=True)
    domain = orm.OneToManyField('Domain', null=True)
    from_ = orm.IPAddressField(null=True)
    gateway = orm.StringField(null=True)
    mask = orm.NetmaskField(required=True)
    name = orm.StringField(required=True)
    network = orm.IPAddressField(required=True)
    to = orm.IPAddressField(null=True)  # (invalid-name) pylint:disable=C0103
    vlanid = orm.StringField(null=True)

    # FIXME: Figure out what these IDs correspond to.
    # dhcp = orm.OneToOneField(null=True)
    # dns = orm.OneToOneField(null=True)
    # tftp = orm.OneToOneField(null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/subnets'
        api_names = (('from_', 'from'),)
        server_modes = ('sat')


class Subscription(orm.Entity):
    """A representation of a Subscription entity."""
    # Subscription Pool uuid
    pool_uuid = orm.StringField()
    # UUID of the system
    system = orm.OneToOneField('System')
    activation_key = orm.OneToOneField('ActivationKey')
    # Quantity of this subscriptions to add
    quantity = orm.IntegerField()
    subscriptions = orm.OneToManyField('Subscription')

    class Meta(object):
        """Non-field information about this entity."""
        api_names = (('pool_uuid', 'id'),)
        api_path = 'katello/api/v2/subscriptions/:id'
        # Alternative paths.
        #
        # '/katello/api/v2/systems/:system_id/subscriptions',
        # '/katello/api/v2/activation_keys/:activation_key_id/subscriptions',
        server_modes = ('sat', 'sam')


class SyncPlan(orm.Entity):
    """A representation of a Sync Plan entity."""
    organization = orm.OneToOneField('Organization', required=True)
    name = orm.StringField(required=True)
    # how often synchronization should run must be one of: none, hourly, daily,
    # weekly.
    interval = orm.StringField(
        choices=('none', 'hourly', 'daily', 'weekly'),
        required=True,
    )
    # start datetime of synchronization
    sync_date = orm.DateTimeField(required=True)
    description = orm.StringField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/organizations/:organization_id/sync_plans'
        server_modes = ('sat')


class SystemPackage(orm.Entity):
    """A representation of a System Package entity."""
    system = orm.OneToOneField('System', required=True)
    # List of package names
    packages = orm.ListField()
    # List of package group names
    groups = orm.ListField()

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/systems/:system_id/packages'
        server_modes = ('sat')


class System(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a System entity."""
    content_view = orm.OneToOneField('ContentView')
    description = orm.StringField()
    environment = orm.OneToOneField('Environment')
    facts = orm.DictField(
        default={u'uname.machine': u'unknown'},
        null=True,
        required=True,
    )
    # guest = orm.OneToManyField()  # FIXME What does this field point to?
    host_collection = orm.OneToOneField('HostCollection')
    installed_products = orm.ListField(null=True)
    last_checkin = orm.DateTimeField()
    location = orm.StringField()
    name = orm.StringField(required=True)
    organization = orm.OneToOneField('Organization', required=True)
    release_ver = orm.StringField()
    service_level = orm.StringField(null=True)
    uuid = orm.StringField()

    # The type() builtin is still available within instance methods, class
    # methods, static methods, inner classes, and so on. However, type() is
    # *not* available at the current level of lexical scoping after this point.
    type = orm.StringField(default='system', required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'katello/api/v2/systems'
        # Alternative paths.
        # '/katello/api/v2/environments/:environment_id/systems'
        # '/katello/api/v2/host_collections/:host_collection_id/systems'
        server_modes = ('sat', 'sam')

    def path(self, which=None):
        """Extend the default implementation of
        :meth:`robottelo.orm.Entity.path`.

        Most entities are uniquely identified by an ID. ``System`` is a bit
        different: it has both an ID and a UUID, and the UUID is used to
        uniquely identify a ``System``.

        Return a path in the format ``katello/api/v2/systems/<uuid>`` if a UUID
        is available and:

        * ``which is None``, or
        * ``which == 'this'``.

        """
        if self.uuid is not None and (which is None or which == 'self'):
            return '{0}/{1}'.format(
                super(System, self).path(which='base'),
                self.uuid
            )
        return super(System, self).path(which)


class TemplateCombination(orm.Entity):
    """A representation of a Template Combination entity."""
    config_template = orm.OneToOneField('ConfigTemplate', required=True)
    environment = orm.OneToOneField('Environment', null=True)
    hostgroup = orm.OneToOneField('HostGroup', null=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = ('api/v2/config_templates/:config_template_id/'
                    'template_combinations')
        server_modes = ('sat')


class TemplateKind(orm.Entity, orm.EntityReadMixin):
    """A representation of a Template Kind entity."""
    # FIXME figure out fields
    # The API does not support the "api/v2/template_kinds/:id" path at all.

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/template_kinds'
        server_modes = ('sat')
        NUM_CREATED_BY_DEFAULT = 8


class UserGroup(orm.Entity):
    """A representation of a User Group entity."""
    name = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/usergroups'
        server_modes = ('sat')


class User(
        orm.Entity, orm.EntityReadMixin, orm.EntityDeleteMixin,
        factory.EntityFactoryMixin):
    """A representation of a User entity.

    The LDAP authentication source with an ID of 1 is internal. It is nearly
    guaranteed to exist and be functioning. Thus, ``auth_source`` is set to "1"
    by default for a practical reason: it is much easier to use internal
    authentication than to spawn LDAP authentication servers for each new user.

    """
    # Passing UTF8 characters for {first,last}name or login yields errors. See
    # bugzilla bug 1144162.
    login = orm.StringField(
        len=(1, 100),
        required=True,
        str_type=('alpha', 'alphanumeric', 'cjk', 'latin1'),
    )
    admin = orm.BooleanField(null=True)
    auth_source = orm.OneToOneField('AuthSourceLDAP', default=1, required=True)
    default_location = orm.OneToOneField('Location', null=True)
    default_organization = orm.OneToOneField('Organization', null=True)
    firstname = orm.StringField(null=True, len=(1, 50))
    lastname = orm.StringField(null=True, len=(1, 50))
    mail = orm.EmailField(required=True)
    password = orm.StringField(required=True)

    class Meta(object):
        """Non-field information about this entity."""
        api_path = 'api/v2/users'
        server_modes = ('sat', 'sam')

    # NOTE: See BZ 1151220
    def create(self, auth=None, data=None):
        """Wrap submitted data within an extra dict."""
        if data is None:
            data = {u'user': self.build(auth=auth)}
        return super(User, self).create(auth, data)
