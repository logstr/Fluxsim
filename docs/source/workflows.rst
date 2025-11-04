Operational Workflows
=====================

This chapter illustrates common workflows for using FluxSim in labs, research sprints, or incident
response simulations. The goal is to treat networks as disposable: spin one up, stress it, collect
telemetry, and tear it down—all while keeping code and configs under version control.

1. Create and Deploy a Flux Network
-----------------------------------

.. code-block:: console

   FluxLab:~ add_flux_network fluxdemo
   FluxLab:~ set_flux_n fluxdemo 3
   FluxLab:~ deploy

Behind the scenes:

* ``fluxsim.dns_utils.write_zone_file`` generates ``dns_config/db.fluxdemo.zone`` with initial
  hostnames.
* ``fluxsim.compose_gen`` rewrites ``docker-compose.yml`` to contain BIND, origin, and proxy
  services.
* ``fluxsim.deploy.deploy`` runs ``docker compose up`` and populates ``monitoring/registry.json``.

2. Monitor Behaviour
--------------------

FluxSim publishes Prometheus metrics and ships raw events to Postgres. The default Grafana dashboard
(`/example dashboards <../monitoring/grafana/dashboards/fluxlab.json>`_) visualises:

* DNS TTL distributions observed by the active probe.
* Query volume ingested by the passive agent.
* Health of each agent container (up/down metrics).

Use the ASCII TUI (`scripts/active_probe_tui.py`) for quick terminal-based monitoring:

.. code-block:: console

   $ python scripts/active_probe_tui.py --endpoint http://localhost:9108
   +-------------------------------+
   |  dns_server_fluxdemo          |
   |    TTL target: 60             |
   |    Last response: 172.60.0.5  |
   +-------------------------------+

3. Capture Telemetry
--------------------

Data lands in Postgres via the ``kafka_ingestor`` service. Example query:

.. code-block:: sql

   SELECT hostname, answer_ip, observed_ttl, seen_at
   FROM probe_events
   WHERE hostname = 'fluxdemo.sim.local'
   ORDER BY seen_at DESC
   LIMIT 20;

For automated analysis, the `examples/notebooks <../examples/notebooks>`_ directory contains Jupyter
notebooks demonstrating TTL drift detection and flux fingerprinting.

4. Scale or Mutate Networks
---------------------------

Need to simulate a surge in capacity? The ``scale_flux_agents`` command in ``fluxsim.deploy`` uses
Docker Compose to resize services and rewrites zone files with new A records.

.. code-block:: console

   FluxLab:~ flux_add_agent fluxdemo
   FluxLab:~ status
   [+] Agents: 4

For load balancers:

.. code-block:: console

   FluxLab:~ add_lb_network lbdemo
   FluxLab:~ set_worker_n lbdemo 5
   FluxLab:~ set_lb_algo lbdemo ip_hash
   FluxLab:~ deploy

5. Tear Down and Reset
----------------------

When finished:

.. code-block:: console

   FluxLab:~ stop
   FluxLab:~ exit
   $ python -c "from fluxsim.state import reset; reset()"

This removes containers/networks and clears the in-memory registry. Zone files remain in
``dns_config/`` for post-mortem study.

Extending FluxSim
-----------------

Integrate FluxSim into your own automation by importing modules directly:

.. code-block:: python

   from fluxsim import compose_gen, deploy, state

   state.reset()
   state.NETWORKS['research'] = state.Net(name='research', kind='flux', subnet_octet=65, subnet='172.65.0.0/24')
   compose_gen.generate('docker-compose.generated.yml')
   deploy.deploy()

The modules in ``fluxsim`` are regular Python packages—Sphinx’s autodoc support (see :doc:`api`)
exposes docstrings so third parties can build on top of the core without installing the CLI.
