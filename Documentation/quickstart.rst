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

.. compiler_substitution:

Compiler Substitution
---------------------

``BuildPal`` provides a drop-in compiler subtitute :file:`bp_cl.exe`. You can
use ``BuildPal`` runner which will detect calls to compiler and replace them
with a call to :file:`bp_cl.exe` on-the-fly. Additionally, you should also
increase max number of paralell jobs.

E.g. instead of calling:

    ninja.exe target -j 4

You should call:

    buildpal_client --run ninja.exe target -j 128

:file:`bp_cl.exe` is small and relatively lightweight, so most modern hardware
should not have any problems in running many concurrently.

.. createprocess_hooking:

CreateProcess Hooking
---------------------

There is a faster, albeit less general and less safe method.

The idea is to intercept all calls a build system makes to the compiler, and to
delegate this work to the farm, completely avoiding compiler process creation on
the client machine. `BuildPal` will try to fool the build system into thinking
that a process was actually created.

This approach works for most build systems. It will not work if the build system
attempts do to anything 'smart' with the (supposedly) created compiler process.
For example, this technique will not work with *MSBuild*.

Run the build as you would with :ref:`compiler_substitution`, but add an additional
flag, `--no-cp`:

    buildpal_client --no-cp --run ninja.exe target -j 128

Here you can go wild with the `-j` option - use as much as your build will allow.
As there is no process creation there will be very little overhead.
