#!/usr/bin/python3
#
# Integration tests for bonds
#
# These need to be run in a VM and do change the system
# configuration.
#
# Copyright (C) 2020 Canonical, Ltd.
# Author: Lukas Märdian <lukas.maerdian@canonical.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys
import subprocess
import unittest

from base import IntegrationTestsBase, test_backends


class _CommonTests():

    # FIXME: Why does this test need to run first in order to pass?
    #   We must leave some dirty state somewhere in the other tests
    def test_1_bridge_vlan(self):
        self.setup_eth(None, True)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br-%s' % self.dev_e_client])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br-data'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br-%s.100' % self.dev_e_client])
        with open(self.config, 'w') as f:
            f.write('''network:
    version: 2
    ethernets:
        %(ec)s:
            mtu: 9000
    bridges:
        br-%(ec)s:
            dhcp4: true
            mtu: 9000
            interfaces: [%(ec)s]
            openvswitch: {}
        br-data:
            openvswitch: {}
            addresses: [192.168.20.1/16]
    vlans:
        br-%(ec)s.100:
            id: 100
            link: br-%(ec)s
            openvswitch: {}''' % {'ec': self.dev_e_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are set up in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge br-%b' % self.dev_e_client.encode(), out)
        self.assertIn(b'''        Port %(ec)b
            Interface %(ec)b''' % {b'ec': self.dev_e_client.encode()}, out)
        self.assertIn(b'''        Port br-%(ec)b.100
            tag: 100
            Interface br-%(ec)b.100
                type: internal''' % {b'ec': self.dev_e_client.encode()}, out)
        self.assertIn(b'    Bridge br-data', out)
        self.assert_iface('br-%s' % self.dev_e_client,
                          ['inet 192.168.5.[0-9]+/16', 'mtu 9000'])  # from DHCP
        self.assert_iface('br-data', ['inet 192.168.20.1/16'])
        self.assert_iface(self.dev_e_client, ['mtu 9000', 'master ovs-system'])
        vid = subprocess.check_output(['ovs-vsctl', 'br-to-vlan',
                                       'br-%s.100' % self.dev_e_client])
        self.assertIn(b'100', vid)
        parent = subprocess.check_output(['ovs-vsctl', 'br-to-parent',
                                          'br-%s.100' % self.dev_e_client])
        self.assertIn(b'br-%b' % self.dev_e_client.encode(), out)

    def test_bridge_base(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovsbr'])
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    %(ec)s: {}
    %(e2c)s: {}
  openvswitch:
    ssl:
      ca-cert: /some/ca-cert.pem
      certificate: /another/certificate.pem
      private-key: /private/key.pem
  bridges:
    ovsbr:
      addresses: [192.170.1.1/24]
      interfaces: [%(ec)s, %(e2c)s]
      openvswitch:
        fail-mode: secure
        controller:
          addresses: [tcp:127.0.0.1, "pssl:1337:[::1]", unix:/some/socket]
''' % {'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge ovsbr', out)
        self.assertIn(b'        Controller "tcp:127.0.0.1"', out)
        self.assertIn(b'        Controller "pssl:1337:[::1]"', out)
        self.assertIn(b'        Controller "unix:/some/socket"', out)
        self.assertIn(b'        fail_mode: secure', out)
        self.assertIn(b'        Port %(ec)b\n            Interface %(ec)b' % {b'ec': self.dev_e_client.encode()}, out)
        self.assertIn(b'        Port %(e2c)b\n            Interface %(e2c)b' % {b'e2c': self.dev_e2_client.encode()}, out)
        # Verify the bridge was tagged 'netplan:true' correctly
        out = subprocess.check_output(['ovs-vsctl', '--columns=name,external-ids', 'list', 'Port'])
        self.assertIn(b'ovsbr\nexternal_ids        : {netplan="true"}', out)
        self.assert_iface('ovsbr', ['inet 192.170.1.1/24'])

    def test_bond_base(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'ovsbr'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'mybond'])
        with open(self.config, 'w') as f:
            f.write('''network:
  ethernets:
    %(ec)s: {}
    %(e2c)s: {}
  bonds:
    mybond:
      interfaces: [%(ec)s, %(e2c)s]
      parameters:
        mode: balance-slb
      openvswitch:
        lacp: off
  bridges:
    ovsbr:
      addresses: [192.170.1.1/24]
      interfaces: [mybond]''' % {'ec': self.dev_e_client, 'e2c': self.dev_e2_client})
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge ovsbr', out)
        self.assertIn(b'        Port mybond', out)
        self.assertIn(b'            Interface %b' % self.dev_e_client.encode(), out)
        self.assertIn(b'            Interface %b' % self.dev_e2_client.encode(), out)
        # Verify the bond was tagged 'netplan:true' correctly
        out = subprocess.check_output(['ovs-vsctl', '--columns=name,external-ids', 'list', 'Port'])
        self.assertIn(b'mybond\nexternal_ids        : {netplan="true"}', out)
        # Verify bond params
        out = subprocess.check_output(['ovs-appctl', 'bond/show', 'mybond'])
        self.assertIn(b'---- mybond ----', out)
        self.assertIn(b'bond_mode: balance-slb', out)
        self.assertIn(b'lacp_status: off', out)
        self.assertIn(b'slave %b: enabled' % self.dev_e_client.encode(), out)
        self.assertIn(b'slave %b: enabled' % self.dev_e2_client.encode(), out)
        self.assert_iface('ovsbr', ['inet 192.170.1.1/24'])

    def test_bridge_patch_ports(self):
        self.setup_eth(None, False)
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br0'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-br', 'br1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'patch0-1'])
        self.addCleanup(subprocess.call, ['ovs-vsctl', '--if-exists', 'del-port', 'patch1-0'])
        with open(self.config, 'w') as f:
            f.write('''network:
  openvswitch:
    ports:
      - [patch0-1, patch1-0]
  bridges:
    br0:
      addresses: [192.168.1.1/24]
      interfaces: [patch0-1]
    br1:
      addresses: [192.168.2.1/24]
      interfaces: [patch1-0]''')
        self.generate_and_settle()
        # Basic verification that the interfaces/ports are set up in OVS
        out = subprocess.check_output(['ovs-vsctl', 'show'])
        self.assertIn(b'    Bridge br0', out)
        self.assertIn(b'''        Port patch0-1
            Interface patch0-1
                type: patch
                options: {peer=patch1-0}''', out)
        self.assertIn(b'    Bridge br1', out)
        self.assertIn(b'''        Port patch1-0
            Interface patch1-0
                type: patch
                options: {peer=patch0-1}''', out)
        self.assert_iface('br0', ['inet 192.168.1.1/24'])
        self.assert_iface('br1', ['inet 192.168.2.1/24'])


@unittest.skipIf("networkd" not in test_backends,
                     "skipping as networkd backend tests are disabled")
class TestOVS(IntegrationTestsBase, _CommonTests):
    backend = 'networkd'


unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))