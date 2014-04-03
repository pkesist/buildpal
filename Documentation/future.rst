.. _future-dev-plans:

Future development plans
========================

* Support more platforms.
    * GCC compiler support (Windows).
    * Clang compiler support (Windows).
    * Linux platform support (GCC/Clang).
    * ...

* Move task delegation logic from Manager to build farm.
    * This would make the farm 'client-aware', providing better performance
      when multiple Clients use the same farm.

* Object file caching support.

* Reporting.
    * Generate detailed report about build process.
