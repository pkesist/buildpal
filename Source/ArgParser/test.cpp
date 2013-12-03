#include "clangOpts_.hpp"

#include "llvm/Option/Arg.h"
#include "llvm/Option/ArgList.h"
#include "llvm/Option/OptTable.h"
#include "llvm/Option/Option.h"
#include "clang/Driver/Options.h"
#include "llvm/Option/OptSpecifier.h"
#include "llvm/Support/raw_ostream.h"
#include "clang/Driver/Options.h"

#include "Python.h"

#include <iostream>
#include <vector>

void printOption( llvm::opt::Option const & option, unsigned indent_c = 0 )
{
    std::string indent;
    for ( unsigned ind = 0; ind < indent_c; ++ind )
        indent += "    ";
    if ( option.isValid() )
    {
        std::cout << indent << "Name " << option.getName().str() << '\n';
        if ( option.getGroup().isValid() )
        {
            std::cout << indent << "GROUP:\n";
            printOption( option.getGroup(), indent_c + 1 );
        }
        if ( option.getAlias().isValid() )
        {
            std::cout << indent << "ALIAS:\n";
            printOption( option.getAlias(), indent_c + 1 );
        }
        std::cout << indent << "HasNoOptAsInput " << option.hasNoOptAsInput() << '\n';
        std::cout << indent << "GetNumArgs " << option.getNumArgs() << '\n';
    }
    else
    {
        std::cout << indent << "No option info.\n";
    }
}

int main( int argc, char const * const argv[] )
{
    unsigned includedFlagsBitmask = clang::driver::options::CLOption;
    unsigned excludedFlagsBitmask = 0;
    unsigned missingArgIndex;
    unsigned missingArgCount;
    llvm::opt::InputArgList const * const args = unaliasedOptTable().ParseArgs( argv + 1, argv + argc, missingArgIndex, missingArgCount, includedFlagsBitmask );
    llvm::opt::InputArgList::arglist_type const & argList = args->getArgs();
    unsigned int index = 0;
    for ( auto arg : argList )
    {
        std::cout << "ARG " << ": " << args->getArgString( index ) << "\n";
        std::cout << "    " << "Owns values " << arg->getOwnsValues() << "\n";
        std::cout << "    " << "Num values " << arg->getNumValues() << "\n";
        for ( unsigned int j = 0; j < arg->getNumValues(); ++j )
        {
            std::cout << "        Value " << j << ": " << arg->getValue( j ) << '\n';
    }
        std::cout << "    Option\n";
        printOption( arg->getOption(), 2 );
        ++index;
    }
    llvm::opt::ArgStringList newArgs;
    for ( auto arg : argList )
        arg->renderAsInput( *args, newArgs );
    for ( auto & arg : newArgs )
        std::cout << arg << ' ';
    std::cout << '\n';
    return 0;
}
