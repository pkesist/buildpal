.. todo::

    This information is out of date...

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

The host machine was not a farm node in distributed compilation.
Tested Boost library version: 1.53.

Environment.
    * 100Mbit/s Ethernet network.
    * Client machine: 4 core i3-M39, 2.67GHz, 8GB RAM
    * Slave #1: 8 core Intel i7-2670QM, 2.20GHz, 6GB RAM
    * Slave #2: 8 core AMD FX-8120, 3.10GHz, 4GB RAM
    * Slave #3: 4 core Intel i5-2430M 2.40GHz, 6GB RAM

    Client machine is the weakest one
    Slave #2 and #3 have similar compile times, even though #2 has twice as many cores.
    Slave #1 is the fastest of the bunch, roughly twice as fast as others.


Slave #1 | 8 jobs | 10:10.44
Slave #2 | 8 jobs | 10:16.77

+---------------+---------+-----------+-----------+-----------+
|               |         |           |           |           |
| type          | jobs #  |  local    |  2 nodes  |  3 nodes  |
|               |         |           |           |           |
+===============+=========+===========+===========+===========+
| regular build | 4  jobs |  8:01.02  |           |           |
+---------------+---------+-----------+-----------+-----------+
| distributed   | 4  jobs |           |  5:11.88  |  5:29.39  |
+---------------+---------+-----------+-----------+-----------+
| distributed   | 16 jobs |           |  2:30.74  |  2:20.66  |
+---------------+---------+-----------+-----------+-----------+
| distributed   | 32 jobs |           |  2:07.34  |  2:06.61  |
+---------------+---------+-----------+-----------+-----------+
| distributed   | 40 jobs |           |  2:06.59  |  2:00.73  |
+---------------+---------+-----------+-----------+-----------+
