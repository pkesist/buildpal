************
Introduction
************

What is it?
===========

``BuildPal`` is a tool for speeding up large C/C++ project build by
distributing compilation to other machines on the network.

Why another distributed compiler?
=================================

The existing open-source distributed compilers have some, if not all, of the
following limitations.

* **No Windows support.**
    
    Pretty much all open-source distributed compilers are designed for \*NIX
    systems, usually targetting GCC.

* **No precompiled header support.**

    It is difficult to speed up project build time if you have to forfeit the
    best single-machine optimization.

* **Sub-optimal task distribution algorithms.**

    Task distribution is usually round-robin, possibly weighted by a number of
    parallel jobs a machine can perform. This does not necessarily work well
    with a farm containing slaves with heterogeneous performance
    characteristics.

* **Slow task propeller.**

    Pushing tasks from the client machine to the farm must be as fast as
    possible. The speed of the leader is the speed of the gang.

``BuildPal`` tries to overcome all of the mentioned limitations.

Features
========

**Easy setup**

    No additional files, other than BuildPal Server, are needed on the
    slave machines. All required files are automatically transferred
    on-demand.

**Node auto-detection**

    Build nodes on LAN are automatically detected and used.

**Build Consistency**

    BuildPal takes care to produce object files which are equivalent
    to the files which would be produced on local compilation.

**Remote preprocessing**

    ``BuildPal`` does not preprocess headers on the local machine.
    Headers used by a source file are collected and transfered to the slave.
    These headers will be reused by the slave machines for subsequent
    compilations.

**PCH support**

    ``BuildPal`` supports precompiled headers. Precompiled headers are
    created locally, on the client machine and are transferred to slave machines
    as needed.

**Self-balancing**

    ``BuildPal`` tries to balance the work between the nodes appropriately by
    keeping track of their statistics, giving more work to faster machines.
    Additionally, if a node runs out of work, it may decide to help out a
    slower node.

Supported platforms and compilers
=================================

At the moment, the only supported compiler toolset is MS Visual C++ compiler.

This includes:

    * ``Visual C++ 2005 (8.0)``
    * ``Visual C++ 2008 (9.0)``
    * ``Visual C++ 2010 (10.0)``
    * ``Visual C++ 2012 (11.0)``

