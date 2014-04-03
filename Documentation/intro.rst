************
Introduction
************

What is it?
===========

*BuildPal* is a tool for speeding up large C/C++ project builds. Inspired by
the `distcc <https://code.google.com/p/distcc/>`_ project, it works by
distributing parts of build process to other machines on the network.
This can reduce build time of a project several times. See :ref:`benchmarks`.

It works by providing a drop-in replacement for compiler executable and
any additional infrastructure needed to make this work.

Features
========

Some notable features of BuildPal suite:

* **Easy setup**
    No additional files, other than BuildPal Server, are needed on the
    slave machines. All required files are automatically transferred
    on-demand.

* **Node auto-detection**
    Build nodes on LAN are automatically detected and used.

* **Build consistency**
    BuildPal takes care to produce object files which are equivalent
    to the files which would be produced on local compilation.

* **Remote preprocessing**
    BuildPal does not preprocess headers on the local machine.
    Headers used by a source file are collected and transfered to the slave.
    These headers will be reused by the slave machines for subsequent
    compilations.

* **PCH support**
    BuildPal supports precompiled headers. Precompiled headers are
    created locally, on the client machine and are transferred to slave machines
    as needed.

* **Self-balancing**
    BuildPal tries to balance the work between the nodes appropriately by
    keeping track of their statistics, giving more work to faster machines.
    Additionally, if a node runs out of work, it may decide to help out a
    slower node.

Supported platforms and compilers
=================================

At the moment the only supported compiler toolset is MS Visual C++ compiler.

This includes:

    * Visual C++ 2005 (8.0)
    * Visual C++ 2008 (9.0)
    * Visual C++ 2010 (10.0)
    * Visual C++ 2012 (11.0)

.. _requirements:

Requirements
============

1. A C/C++ project (duh) which uses a build system capable of running parallel
   tasks.

2. A main build machine (client machine) connected to a Local-Area Network.

3. As many as possible machines (slaves) on LAN capable of running the compiler
   your C/C++ project uses.
    * Given that the only compiler currently supported is MSVC, this means that
      all slave machines need to run Windows.
