.. todo::

    INCOMPLETE

.. _benchmarks:

Benchmarks
==========

Currently ``BuildPal`` is mainly tested by building :ref:`boost-libs`.
Boost libraries make heavy use of preprocessor, and are thus ideal candidates
for testing both speed and sanity.

Building Boost was done with the following command, after modifying
Boost.Build to use ``BuildPal``'s compiler instead of the native msvc
compiler executable::

    bjam stage --stagedir=. -a -j ##

The host machine was not a part of farm.
Tested Boost library version: 1.53.

Environment.
    * 100Mbit/s Ethernet network.
    * Client machine: 4 core i3-M39, 2.67GHz, 8GB RAM
    * Slave #1: 8 core Intel i7-2670QM, 2.20GHz, 6GB RAM
    * Slave #2: 8 core AMD FX-8120, 3.10GHz, 4GB RAM
    * Slave #3: 4 core Intel i5-2430M 2.40GHz, 6GB RAM

.. todo::

    Create table with measurements.