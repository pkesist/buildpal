************
Introduction
************

What is it?
===========

*BuildPal* is a tool for speeding up large C/C++ project builds. Inspired by
the `distcc <https://code.google.com/p/distcc/>`_ project, it works by
distributing parts of build process to other machines on the network.

Why another distributed compiler?
=================================

The existing open-source distributed compilers have some, if not all, of the
following limitations.

* No Windows support.
    
    Pretty much all open-source distributed compilers are designed for \*NIX
    systems, usually targetting GCC compiler.

* No precompiled header support.

* Sub-optimal task scheduling algorithms.

    Task scheduling is usually round-robin, which does not work well with farms
    containing slaves with heterogeneous performance characteristics.

* Slow task propeller.

    Client side task propeller should be as fast as possible. As C/C++
    preprocessing is quite CPU intensive, client-side source file preprocessing
    is very limiting [#f1]_.

BuildPal tries to overcome all of the mentioned limitations.

Features
========

Easy setup
----------

No additional files, other than BuildPal Server, are needed on the
slave machines. All required files are automatically transferred
on-demand.

Slave auto-detection
--------------------

Build nodes on LAN are automatically detected and used.

Build Consistency
-----------------

BuildPal takes care to produce object files which are equivalent
to the files which would be produced on local compilation.

Remote preprocessing
--------------------

BuildPal does not preprocess headers on the local machine.
Headers used by a source file are collected and transfered to the slave.
These headers will be reused by the slave machines for subsequent
compilations.

PCH support
-----------

BuildPal supports precompiled headers. Precompiled headers are
created locally, on the client machine and are transferred to slave machines
as needed.

Self-balancing
--------------

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

.. rubric:: footnotes

.. [#f1] MS Visual C++ compiler does not really have a preprocessing step when
    compiling. It tries to optimize the compilation processes and memory usage
    by going through the file only once, performing both preprocesing and
    tokenization at once, line by line. Manually running the preprocessor, and
    then compiling the preprocessed result significantly increases the compilation
    time. Consequently, trying to distribute compilation of locally preprocessed
    source files apriori incurs a time penalty. This approach can generate
    work for only 2-3 additional slaves at best. To make matters worse, MSVC++
    is generally `unable \
    <http://connect.microsoft.com/VisualStudio/feedback/details/783043/>`_
    to compile preprocessed output it generates.
