//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef utility_HPP__C365973E_280B_4A04_B419_EEE35B274D91
#define utility_HPP__C365973E_280B_4A04_B419_EEE35B274D91
//------------------------------------------------------------------------------
#include <llvm/ADT/StringRef.h>
#include <atomic>
//------------------------------------------------------------------------------

namespace clang
{
    class Preprocessor;
    class MacroDirective;
}

llvm::StringRef macroValueFromDirective( clang::Preprocessor const & preprocessor, llvm::StringRef const macroName, clang::MacroDirective const * def );


typedef std::atomic<bool> SpinLockMutex;

struct SpinLock
{
    SpinLockMutex & mutex_;
    SpinLock( SpinLockMutex & mutex ) : mutex_( mutex )
    {
        while ( mutex_.exchange( true, std::memory_order_acquire ) );
    }

    ~SpinLock()
    {
        mutex_.store( false, std::memory_order_release );
    }
};


//------------------------------------------------------------------------------
#endif