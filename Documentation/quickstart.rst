Quick Start
###########

Requirements
============

1. A C/C++ project (duh) using a build system capable of running parallel
   tasks.

2. A client build machine connected to a Local-Area Network.

3. As many as possible machines (slaves) on LAN capable of running the compiler
   your C/C++ project uses.

    * Given that the only compiler currently supported is MSVC, this means that
      all slave machines need to run Windows.

Setting up the Server (slave) nodes
===================================

On each slave on the network do the following:

* Install BuildPal. This will create 'BuildPal Server' shortcut on your desktop.
* Run the shortcut.

.. note:

    There is no need to explicitly specify TCP port. Each server is
    automatically discovered (via UDP multicast).

.. note:

    Slaves do not need to have compiler pre-installed.

Setting up the Client
=====================

* Install BuildPal on the Client machine.
* Run the 'BuildPal Manager' shortcut.

Running the distributed build can be accomplished in two ways. Neither requires
changes to your project build system.

.. createprocess_hooking:

CreateProcess Hooking
---------------------

This is the best way to run distributed build with `BuildPal`. Unfortunately, it
does not generally work.

The idea is to intercept all calls a build system makes to the compiler, and to
delegate this work to the farm, completely avoiding compiler process creation on
the client machine. `BuildPal` will try to fool the build system into thinking
that a process was actually created. This approach works for most build systems.
It will not work if the build system attempts do to something smart with the
(supposedly) created compiler process.

This approach is also the most efficient -- process spawning on Windows is quite
expensive.

Run the build as you usually would, but prepend `buildpal_client --run`. You
should also increase max number of parallel jobs.

For example, instead of running::

    ninja.exe target -j 4

You should run::

    buildpal_client --run ninja.exe target -j 128

You can go wild with the `-j` option - use as much as your build will allow. As
there is no process creation there will be little or no overhead.

.. compiler_substitution:

Compiler Substitution
---------------------

If the above approach fails with your build system, there is an alternative.
BuildPal installation has a drop-in compiler substitute :file:`bp_cl.exe`.

The invocation is similar to the one above::

    buildpal_client --cs --run ninja.exe target -j 128

Note the extra `--cs` flag.

With this approach, a real process will be created, so excercise caution when
passing determining `-j`. On the other hand, :file:`bp_cl.exe` is small and
relatively lightweight, so most modern hardware should not have any problems
in running many concurrently.

