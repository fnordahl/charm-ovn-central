# Copyright 2019 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import io
import mock
import os

import charms_openstack.test_utils as test_utils

import charm.openstack.ovn_central as ovn_central


class TestOVNConfigProperties(test_utils.PatchHelper):

    def test_ovn_key(self):
        self.assertEquals(ovn_central.ovn_key(None),
                          os.path.join(ovn_central.OVS_ETCDIR, 'key_host'))

    def test_ovn_cert(self):
        self.assertEquals(ovn_central.ovn_cert(None),
                          os.path.join(ovn_central.OVS_ETCDIR, 'cert_host'))

    def test_ovn_ca_cert(self):
        cls = mock.MagicMock()
        cls.charm_instance.name = mock.PropertyMock().return_value = 'name'
        self.assertEquals(ovn_central.ovn_ca_cert(cls),
                          os.path.join(ovn_central.OVS_ETCDIR, 'name.crt'))


class Helper(test_utils.PatchHelper):

    def setUp(self):
        super().setUp()
        self.patch_release(ovn_central.OVNCentralCharm.release)
        self.target = ovn_central.OVNCentralCharm()

    def patch_target(self, attr, return_value=None):
        mocked = mock.patch.object(self.target, attr)
        self._patches[attr] = mocked
        started = mocked.start()
        started.return_value = return_value
        self._patches_start[attr] = started
        setattr(self, attr, started)


class TestOVNCentralCharm(Helper):

    def test_install(self):
        self.patch_object(ovn_central.charms_openstack.charm.OpenStackCharm,
                          'install')
        self.patch_object(ovn_central.os.path, 'islink')
        self.islink.return_value = False
        self.patch_object(ovn_central.os, 'symlink')
        self.patch_target('configure_source')
        self.target.install()
        self.islink.assert_called_once_with(
            '/etc/systemd/system/ovn-central.service')
        self.symlink.assert_called_once_with(
            '/dev/null',
            '/etc/systemd/system/ovn-central.service')
        self.install.assert_called_once_with()
        self.configure_source.assert_called_once_with()

    def test__default_port_list(self):
        self.assertEquals(
            self.target._default_port_list(),
            [ovn_central.DB_NB_PORT, ovn_central.DB_SB_PORT])

    def test_ports_to_check(self):
        self.target._default_port_list = mock.MagicMock()
        self.target.ports_to_check()
        self.target._default_port_list.assert_called_once_with()

    def test_enable_services(self):
        self.patch_object(ovn_central.ch_core.host, 'service_resume')
        self.target.check_if_paused = mock.MagicMock()
        self.target.check_if_paused.return_value = ('status', 'message')
        self.target.enable_services()
        self.target.check_if_paused.assert_called_once_with()
        self.assertFalse(self.service_resume.called)
        self.target.check_if_paused.return_value = (None, None)
        self.target.enable_services()
        self.service_resume.assert_called_once_with('ovn-central')

    def test_run(self):
        self.patch_object(ovn_central.subprocess, 'run')
        self.patch_object(ovn_central.ch_core.hookenv, 'log')
        self.target.run('some', 'args')
        self.run.assert_called_once_with(
            ('some', 'args'),
            stdout=ovn_central.subprocess.PIPE,
            stderr=ovn_central.subprocess.STDOUT,
            check=True,
            universal_newlines=True)

    def test_join_cluster(self):
        self.patch_target('run')
        self.target.join_cluster('/a/db.file',
                                 'aSchema',
                                 ['ssl:a.b.c.d:1234'],
                                 ['ssl:e.f.g.h:1234', 'ssl:i.j.k.l:1234'])
        self.run.assert_called_once_with(
            'ovsdb-tool', 'join-cluster', '/a/db.file', 'aSchema',
            'ssl:a.b.c.d:1234', 'ssl:e.f.g.h:1234', 'ssl:i.j.k.l:1234')

    def test_configure_tls(self):
        self.patch_object(ovn_central.reactive, 'is_flag_set')
        self.patch_target('get_certs_and_keys')
        self.get_certs_and_keys.return_value = [{
            'cert': 'fakecert',
            'key': 'fakekey',
            'cn': 'fakecn',
            'ca': 'fakeca',
            'chain': 'fakechain',
        }]
        with mock.patch('builtins.open', create=True) as mocked_open:
            mocked_file = mock.MagicMock(spec=io.FileIO)
            mocked_open.return_value = mocked_file
            self.target.configure_cert = mock.MagicMock()
            self.target.run = mock.MagicMock()
            self.is_flag_set.return_value = True
            self.target.configure_tls()
            mocked_open.assert_called_once_with(
                '/etc/openvswitch/ovn.crt', 'w')
            mocked_file.__enter__().write.assert_called_once_with(
                'fakeca\nfakechain')
            self.target.configure_cert.assert_called_once_with(
                ovn_central.OVS_ETCDIR,
                'fakecert',
                'fakekey',
                cn='host')
            self.target.run.assert_has_calls([
                mock.call('ovs-vsctl',
                          'set-ssl',
                          '/etc/openvswitch/key_host',
                          '/etc/openvswitch/cert_host',
                          '/etc/openvswitch/ovn.crt'),
                mock.call('ovs-vsctl',
                          'set',
                          'open',
                          '.',
                          'external-ids:ovn-remote=ssl:127.0.0.1:6642'),
                mock.call('ovn-nbctl',
                          'set-connection',
                          'pssl:6641'),
                mock.call('ovn-sbctl',
                          'set-connection',
                          'pssl:6642'),
            ])
            self.is_flag_set.return_value = False
            self.target.run.reset_mock()
            self.target.configure_tls()
            self.target.run.assert_has_calls([
                mock.call('ovs-vsctl',
                          'set-ssl',
                          '/etc/openvswitch/key_host',
                          '/etc/openvswitch/cert_host',
                          '/etc/openvswitch/ovn.crt'),
                mock.call('ovs-vsctl',
                          'set',
                          'open',
                          '.',
                          'external-ids:ovn-remote=ssl:127.0.0.1:6642'),
            ])
