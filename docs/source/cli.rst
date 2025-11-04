CLI Reference
=============

FluxSim exposes a `riposte <https://github.com/logstr/riposte>`_-powered shell. Launch it by simply
running ``fluxsim`` after you’ve installed the package or activated an editable checkout.

Session Basics
--------------

.. code-block:: console

   $ fluxsim
   Network Behavior Simulator (Flux, LB, CDN, Static)
   FluxLab:~ help

Type ``help`` (or ``?``) to list commands; ``help <command>`` displays detailed usage. All commands
mutate shared state stored in ``fluxsim.state`` and persist snapshots to
``monitoring/registry.json``.

Lifecycle Commands
------------------

``add_normal_network <name>``
    Create a subnet containing a single origin server with authoritative DNS.

``add_flux_network <name>``
    Configure an origin server plus a proxy agent pool whose addresses rotate in DNS.

``add_lb_network <name>``
    Create an NGINX load balancer fronting a worker pool.

``add_cdn_network <name>``
    Provision an origin server plus configurable CDN edge containers.

``deploy``
    Regenerate ``docker-compose.yml`` and bring the stack up. Zone files, agent manifests, and
    resolver configs are recalculated on each deploy.

``stop``
    Tear down the compose stack while leaving state (zone files, registry) intact.

Inspecting State
----------------

``status``
    Summarises configured networks, listing their IPs, TTLs, and quick diagnostic commands.

``doctor``
    Prints module import paths, ensuring CLI, deploy, and compose modules share state correctly.

``client_browse <host>``
    Runs ``lynx -dump`` inside ``dns_client_test`` so you can inspect rendered HTML via
    the simulated resolver chain.

``desktop_start`` / ``desktop_stop``
    Launch or remove the optional noVNC desktop container for GUI tooling.

DNS and Scaling Operations
--------------------------

``set_flux_n <network> <count>``
    Adjust the number of proxy agents in a flux network; triggers redeploy to refresh zone data.

``set_worker_n``, ``set_cdn_n``
    Update worker or CDN counts and redeploy.

``set_flux_selector <network> <random|roundrobin>``
    Change the algorithm used when writing A records for flux networks.

``set_lb_algo <network> <round_robin|ip_hash>``
    Toggle NGINX load balancer affinity.

``set_ttl <network> <seconds>``
    Update zone TTL by rewriting the BIND zone file and reloading the authoritative server.

Example Workflow
----------------

.. code-block:: console

   FluxLab:~ add_flux_network fluxy
   [+] Added flux 'fluxy' (172.60.0.0/24)
   FluxLab:~ set_flux_n fluxy 4
   FluxLab:~ deploy
   [+] fluxy: refresh wrote 4 agent IP(s) to dns_config/flux_agents_fluxy.txt
   [+] Wrote resolv for client with 1 nameserver(s): 172.60.0.53
   FluxLab:~ status
     [FLUX] fluxy  Subnet:  172.60.0.0/24
   [+] DNS IP: 172.60.0.53   Domain: fluxy.sim.local
   [+] Agents: 4
   [+] Test:   docker compose exec dns_client_test dig @172.60.0.53 fluxy.sim.local +short

   FluxLab:~ client_browse fluxy.sim.local
   http://fluxy.sim.local/
   ...
