.. _benchmarks:

Benchmarks
==========

Environment.
    * 100Mbit/s Ethernet network.
    * Client machine: 4 core i3-M39, 2.67GHz, 8GB RAM
    * Slave #1: 8 core Intel i7-2670QM, 2.20GHz, 6GB RAM
    * Slave #2: 8 core AMD FX-8120, 3.10GHz, 4GB RAM
    * Slave #3: 4 core Intel i5-2430M 2.40GHz, 6GB RAM

Benchmarks are done by compiling real code. As Boost and Clang are required for
BuildPal itself, it was only natural to use these libraries for benchmarking.

Boost
-----

Tested command for building boost is::

    b2 stage --stagedir=. link=static runtime-link=shared variant=release -j64 toolset=msvc-11.0 --build-type=complete -a

The numbers in the table are seconds it took to build the project. Each entry is
the mean of 10 consecutive builds, along with standard deviation.

+--------+-------------+------------+------------------+-------------------+-------------------+
|        | regular     | local      | client + 1 slave | client + 2 slaves | client + 3 slaves |
+========+=============+============+==================+===================+===================+
| client |             |            |                                                          |
+--------+-------------+------------+------------------+-----+-------------+-------------------+
|slave #1| 226.6±13.3  | 278.6±14.0 |   242.6±2.3      |#2+#3|  211.1±2.8  |                   |
+--------+-------------+------------+------------------+-----+-------------+                   |
|slave #2| 411.5±6.8   | 529.9±9.6  |   377.2±5.2      |#1+#3|  166.0±1.7  |     142.0±4.0     |
+--------+-------------+------------+------------------+-----+-------------+                   |
|slave #3| 493.7±4.74  |            |                  |#1+#2|  162.4±4.1  |                   |
+--------+-------------+------------+------------------+-----+-------------+-------------------+

* regular - regular project build, without BuildPal
* local - BuildPal, with a single server running locally
