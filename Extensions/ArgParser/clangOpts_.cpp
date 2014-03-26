#include "clangOpts_.hpp"

#include "llvm/Option/OptTable.h"
#include "llvm/Option/Option.h"
#include "clang/Driver/Options.h"

#define PREFIX(NAME, VALUE) static const char * const NAME[]= VALUE;
#include "clang/Driver/Options.inc"
#undef PREFIX

using namespace llvm::opt;
using namespace clang::driver::options;
static const llvm::opt::OptTable::Info unaliasedInfoTable[] = {
#define OPTION(PREFIX, NAME, ID, KIND, GROUP, ALIAS, ALIASARGS, FLAGS, PARAM, \
               HELPTEXT, METAVAR)   \
  { PREFIX, NAME, HELPTEXT, METAVAR, OPT_##ID, Option::KIND##Class, PARAM, \
    FLAGS, OPT_##GROUP, 0, 0 },
#include "clang/Driver/Options.inc"
#undef OPTION
};

namespace {
struct UnaliasedOptionTable : public llvm::opt::OptTable {
    UnaliasedOptionTable() : llvm::opt::OptTable( unaliasedInfoTable, sizeof( unaliasedInfoTable ) / sizeof( unaliasedInfoTable[0] ) ) {}
} unaliasedOptTable_static; }

llvm::opt::OptTable & unaliasedOptTable()
{
    return unaliasedOptTable_static;
}


