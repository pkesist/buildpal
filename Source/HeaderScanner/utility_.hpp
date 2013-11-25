//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef utility_HPP__C365973E_280B_4A04_B419_EEE35B274D91
#define utility_HPP__C365973E_280B_4A04_B419_EEE35B274D91
//------------------------------------------------------------------------------
#include <llvm/ADT/StringRef.h>
#include <atomic>
#include <unordered_set>
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

template <typename T, typename Tag=T>
struct FlyweightStorage : public std::unordered_set<T>
{
public:
    const_iterator insert( T const & t )
    {
        SpinLock const lock( mutex );
        return std::unordered_set<T>::insert( t ).first;
    }

    static FlyweightStorage & get() { return storage; }

private:
    SpinLockMutex mutex;
    static FlyweightStorage storage;
};

template <typename T, typename Tag>
FlyweightStorage<T, Tag> FlyweightStorage<T, Tag>::storage;

template<typename T, typename Tag=T>
struct Flyweight
{
    typedef FlyweightStorage<T, Tag> Storage;

    Flyweight( T const & t ) : iter_( Storage::get().insert( t ) ) {}
    template<typename A1>
    Flyweight( A1 a1 ) : iter_( Storage::get().insert( T( a1 ) ) ) {}
    template<typename A1, typename A2>
    Flyweight( A1 a1, A2 a2 ) : iter_( Storage::get().insert( T( a1, a2 ) ) ) {}

    Flyweight( Flyweight const & other ) : iter_( other.iter_ ) {}
    Flyweight & operator=( Flyweight const & other ) { iter_ = other.iter_; return *this; }

    T const & get() const { return *iter_; }
    operator T const & () const { return get(); }

    bool operator==( Flyweight<T, Tag> const & other )
    {
        return iter_ == other.iter_;
    }

private:
    typename Storage::const_iterator iter_;
};

template<typename T, typename Tag>
bool operator<( Flyweight<T, Tag> const & a, Flyweight<T, Tag> const & b ) { return a.get() < b.get(); }


//------------------------------------------------------------------------------
#endif