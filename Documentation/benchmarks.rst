.. todo::

    This information is out of date...

.. _benchmarks:

Benchmarks
==========

Currently BuildPal is mainly tested by building :ref:`boost-libs`.
Boost libraries make heavy use of preprocessor, and are thus ideal candidates
for testing both speed and sanity.

Building Boost was done with the following command, after modifying
Boost.Build to use BuildPal's compiler instead of the native msvc
compiler executable::

    bjam stage --stagedir=. -a -j ##

The host machine was not a farm node in distributed compilation.
Tested Boost library version: 1.53.

Environment.
    * 100Mbit/s Ethernet network.
    * Client machine: HP Pavillion g7 notebook with Intel i3 processor (4 cores).
    * Slave #1. Dell notebook with i7 processor (8 cores).
    * Slave #2. Speedtest (8 cores).
    * Slave #3. Asus notebook, 4 cores.

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
