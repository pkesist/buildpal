.. _benchmarks:

Benchmarks
==========

Environment
-----------

* 100Mbit/s Ethernet network.
* Client machine: 4 core i3-M39, 2.67GHz, 8GB RAM
* Slave #1: 8 core Intel i7-2670QM, 2.20GHz, 6GB RAM
* Slave #2: 8 core AMD FX-8120, 3.10GHz, 4GB RAM
* Slave #3: 4 core Intel i5-2430M 2.40GHz, 6GB RAM

The client machine is by far the weakest one. Build times are about 4-5 times
longer than on #1.

Benchmarks are done by compiling real code. As Boost and Clang are required for
BuildPal itself, it was only natural to use these libraries for benchmarking.

Boost
-----

Tested command for building boost is::

    b2 stage --stagedir=. link=static runtime-link=shared -j64 toolset=msvc-11.0 --build-type=complete -a

The numbers in the table are seconds it took to build the project. Each entry is
the mean of 10 consecutive builds, along with standard deviation.

+--------+-------------+------------+------------------+-------------------+-------------------+
|        | regular [*]_| local [**]_| client + 1 slave | client + 2 slaves | client + 3 slaves |
+========+=============+============+==================+===================+===================+
| client |             |            |                                                          |
+--------+-------------+------------+------------------+-----+-------------+-------------------+
|slave #1| 220.3±2.8   | 272.3±4.0  |   242.6±2.3      |#2+#3|  211.1±2.8  |                   |
+--------+-------------+------------+------------------+-----+-------------+                   |
|slave #2| 294.6±7.9   | 400.2±3.5  |   377.2±5.2      |#1+#3|  166.0±1.7  |     128.5±4.0     |
+--------+-------------+------------+------------------+-----+-------------+                   |
|slave #3| 419.1±12.9  | 466.6±15.9 |   446.5±5.1      |#1+#2|  153.8±4.1  |                   |
+--------+-------------+------------+------------------+-----+-------------+-------------------+

.. [*] regular project build, without BuildPal
.. [**] BuildPal build with a single server running locally

Clang
-----

.. todo::

    Measure Clang build times.