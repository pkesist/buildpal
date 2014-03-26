#ifndef _MSC_VER
#include <cstdint>
#endif

namespace llvm { namespace opt { class OptTable; } }

llvm::opt::OptTable & unaliasedOptTable();
