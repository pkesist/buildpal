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
BuildPal itself, it was only logical to use these libraries for benchmarking.

+--------+-------------+------------------+-------------------+-------------------+
|        | local       | client + 1 slave | client + 2 slaves | client + 3 slaves |
+========+=============+==================+===================+===================+
| client |             |                  |                   |                   |
+--------+-------------+------------------+-------------------+-------------------+
|slave #1|             |                  |                   |                   |
+--------+-------------+------------------+-------------------+                   +
|slave #2|             |                  |                   |                   |
+--------+-------------+------------------+-------------------+                   +
|slave #3|             |                  |                   |                   |
+--------+-------------+------------------+-------------------+-------------------+

.. todo::

    INCOMPLETE