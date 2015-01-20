from midonetclient.api import MidonetApi
from midonetclient.router import Router
from midonetclient import resource_base
from midonetclient import vendor_media_type
from eucaops import Eucaops
from eutester.sshconnection import SshConnection
from eutester.euinstance import EuInstance
from eutester.eulogger import Eulogger
from boto.ec2.instance import Instance
from prettytable import PrettyTable
import requests
import re

class arptable(resource_base.ResourceBase):
    def __init__(self, uri, dto, auth):
        super(arptable, self).__init__(uri, dto, auth)

    def get_ip(self):
        return self.dto.get('ip')

    def get_mac(self):
        return self.dto.get('mac')

    def get_macaddr(self):
        return self.dto.get('macAddr')

class MidoDebug(object):
    def __init__(self, midonet_api_host, midonet_api_port='8080', midonet_username=None,
                 midonet_password=None, eutester_config=None, eutester_password=None, tester=None):
        self.midonet_api_host = midonet_api_host
        self.midonet_api_port = midonet_api_port
        self.midonet_username = midonet_username
        self.midonet_password = midonet_password
        self.mapi = MidonetApi(base_uri='http://{0}:{1}/midonet-api'
                          .format(self.midonet_api_host, self.midonet_api_port),
                          username=self.midonet_username, password=self.midonet_password)

        self.tester = tester
        if not self.tester:
            self.tester = Eucaops(config_file=eutester_config, password=eutester_password)
        self.logger = Eulogger(identifier='MidoDebug:{0}'.format(self.midonet_api_host))

    def debug(self, msg):
        self.logger.log.debug(msg)

    def _indent_table_buf(self, table):
        buf = str(table)
        ret_buf = ""
        for line in buf.splitlines():
                ret_buf += '\t{0}\n'.format(line)
        return ret_buf


    def _get_instance(self, instance):
        if not isinstance(instance, Instance):
            if isinstance(instance, str):
                fetched_ins = self.tester.get_instances(idstring=instance)
            if not fetched_ins:
                raise ValueError('Could not find instance {0} on system'.format(instance))
            instance = fetched_ins
        return instance

    def get_all_routers(self, search_dict={}, eval_op=re.search, query=None):
        """
        Returns all routers that have attributes and attribute values as defined in 'search_dict'
        """
        routers = self.mapi.get_routers(query=None)
        remove_list = []
        for key in search_dict:
            for router in routers:
                if hasattr(router, key):
                    try:
                        if eval_op(str(search_dict[key]), str(getattr(router, key)) ) :
                            continue
                    except:
                        self.debug('Error while evaluating -> {0}("{1}","{2}")'
                               .format(eval_op, search_dict[key], getattr(router,key)))
                        raise
                remove_list.append(router)
            for router in remove_list:
                if router in routers:
                    routers.remove(router)
        return routers

    def get_router_for_instance(self,instance):
        instance = self._get_instance(instance)
        self.debug('Getting router for instance:{0}, vpc:{1}'.format(instance.id,  instance.vpc_id))
        routers = self.get_all_routers(search_dict={'name':instance.vpc_id})
        if len(routers) != 1:
            raise ValueError('Expected to find 1 matching router for instance:{0}, found:{1}'
                             .format(instance.id, routers))
        router = routers[0]
        self.debug('Found router:{0} for instance:{1}'.format(router.get_name(), instance.id))
        return router

    def show_routers_brief(self, routers=None, printme=True):
        """
        Show a list of of routers, or by default all routers available in the current session
        context. Use show_routers to display the route information of each router.
        """
        if routers is None:
            routers = self.get_all_routers()
        if not isinstance(routers,list):
            routers = [routers]
        pt = PrettyTable(['Name', 'AdminState', 'ID', 'InboundChain', 'OutboundChain','T-ID' ])
        for router in routers:
            pt.add_row([router.get_name(),router.get_admin_state_up(), router.get_id(), router.get_inbound_filter_id(),
                       router.get_outbound_filter_id(), router.get_tenant_id()])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        return pt

    def show_routes(self, routes, printme=True):
        '''
        show a list of provided route objects
        '''
        if not isinstance(routes,list):
            routes = [routes]
        pt = PrettyTable(['Destination','Source', 'nexthopGW', 'nexthop', 'weight', 'ID'])
        for route in routes:
            pt.add_row(['{0}/{1}'.format(route.get_dst_network_addr(),
                                         route.get_dst_network_length()),
                        '{0}/{1}'.format(route.get_src_network_addr(),
                                         route.get_src_network_length()),
                        route.get_next_hop_gateway(),
                        route.get_next_hop_port(),
                        route.get_weight(),
                        route.get_id()
                        ])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        return pt

    def show_routers(self, routers=None, printme=True):
        '''
        Show a list of routers, or by default all routers in the current session context
        '''
        buf = ""
        if routers is None:
            routers = self.get_all_routers()
        if not isinstance(routers,list):
            routers = [routers]
        for router in routers:
            buf += self.show_router_summary(router, showchains=False, printme=False)
        self.debug(buf)


    def show_router_summary(self, router, showchains=True, printme=True):
        """
        Show a single routers summary
        """
        t1 = self._indent_table_buf(self.show_routers_brief(routers=[router], printme=False))
        t2 = self._indent_table_buf(self.show_routes(routes=router.get_routes(), printme=False))
        t3 = self._indent_table_buf(self.show_ports(ports=router.get_ports(), printme=False))
        buf = ('\nROUTER: "{0}"\n{1}\n\tROUTES:\n{2}\n\tPORTS:\n{3}\n\n'.format(
            router.get_name(),t1,t2,t3))
        if printme:
            self.debug('\n{0}\n'.format(buf))
        return buf



    def show_ports(self, ports, printme=True):
        """
        Show formatted info about a specific port
        """
        buf = ""
        if not isinstance(ports,list):
            ports = [ports]
        pt = None
        for port in ports:
            bgps = 0
            try:
                if port.dto.get('bgps'):
                    bgps =  port.get_bgps()
                    if bgps:
                        bgps = len(bgps)
                    else:
                        bgps = 0
            except Exception, E:
                bgps = 'ERROR'
                self.debug('Error fetching bgps from port:{0}, err"{1}'.format(port.get_id(), E))
            if not pt:
                pt = PrettyTable(['UP','PORT ID', 'BGPS', 'IPADDR', 'NETWORK', 'MAC', 'TYPE', 'PEER ID'])
            pt.add_row([port.get_admin_state_up(),
                        port.get_id(),
                        bgps,
                        port.get_port_address(),
                        "{0}/{1}".format(port.get_network_address(), port.get_network_length()),
                        port.get_port_mac(),
                        port.get_type(),
                        port.get_peer_id()])

            if bgps and bgps != "ERROR":
                lines = []
                for line in str(pt).splitlines():
                    line = line.strip()
                    if line:
                        lines.append(line)
                footer = lines[-1]
                buf += "\n".join(lines) + '\n'
                pt = None
                buf += self._indent_table_buf(self.show_bgps(bgps, printme=False))
                buf += footer +'\n'
        if pt:
            buf += str(pt)
        if printme:
            self.debug('\n{0}\n'.format(pt))
        return buf


    def show_bgps(self, bgps, printme=True):
        if not isinstance(bgps,list):
            bgps = [bgps]
        pt = PrettyTable(['PORT ID', 'BGP ID', 'PEER ADDR', 'LOCAL AS', 'PEER AS', 'AD ROUTES'])
        for bgp in bgps:
            pt.add_row([bgp.dto.get('portId', ""),
                        bgp.get_id(),
                        bgp.get_peer_addr(),
                        bgp.get_local_as(),
                        bgp.get_peer_as(),
                        self._format_ad_routes(bgp.get_ad_routes())])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        return pt


    def _format_ad_routes(self, ad_routes):
        adrs =[]
        if not isinstance(ad_routes,list):
            ad_routes = [ad_routes]
        for adr in ad_routes:
            adrs.append('{0}/{1}'.format(adr.get_nw_prefix(), adr.get_prefix_length()))
        return adrs



    def show_bridges(self, bridges=None, printme=True):
        if bridges:
            if not isinstance(bridges,list):
                bridges = [bridges]
        else:
            bridges = self.mapi.get_bridges(query=None)
        printbuf = ""
        for bridge in bridges:
            buf = ""
            pt = PrettyTable(['BRIDGE NAME', 'ID', 'TENANT', 'Vx LAN PORT'])
            pt.add_row([bridge.get_name(), bridge.get_id(), bridge.get_tenant_id(),
                       bridge.get_vxlan_port()])
            title = 'BRIDGE SUMMARY:"{0}"'.format(bridge.get_name())
            box = PrettyTable([title])
            box.align[title] = 'l'

            buf += self._indent_table_buf(str(pt))
            buf += "\tBRIDGE PORTS:\n"
            buf += self._indent_table_buf(self.show_ports(bridge.get_ports(), printme=False))
            buf += "\tBRIDGE ARP TABLE:\n"
            buf += self._indent_table_buf(self.show_bridge_arp_table(bridge=bridge, printme=False))
            buf += "\tDHCP SUBNETS:\n"
            buf += self._indent_table_buf(self.show_bridge_dhcp_subnets(bridge, printme=False))
            box.add_row([buf])
            printbuf += str(box) + "\n"
        if printme:
            self.debug('\n{0}\n'.format(printbuf))
        else:
            return printbuf

    def show_bridge_dhcp_subnets(self, bridge, printme=True):
        pt = PrettyTable(['SUBNET', 'SERVER ADDR', 'DefaultGW', 'DNS SERVERS', 'STATE'])
        for subnet in bridge.get_dhcp_subnets():
            pt.add_row(["{0}/{1}".format(subnet.get_subnet_prefix(), subnet.get_subnet_length()),
                       subnet.get_server_addr(),
                       subnet.get_default_gateway(),
                       ",".join(str(dns) for dns in subnet.get_dns_server_addrs()),
                       subnet.dto.get('enabled')])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        return pt


    def get_bridge_arp_table(self, bridge):
        table = bridge.get_children(bridge.dto['arpTable'],
                                    query=None,
                                    headers={"Accept":""},
                                    clazz=arptable)
        return table

    def show_bridge_arp_table(self, bridge, printme=True):
        pt = PrettyTable(['IP', 'MAC', 'MAC ADDR'])
        table = self.get_bridge_arp_table(bridge)
        for entry in table:
            pt.add_row([entry.get_ip(), entry.get_mac(), entry.get_macaddr()])
        if printme:
            self.debug('\n{0}\n'.format(pt))
        return pt








