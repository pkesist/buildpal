//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef utility_HPP__C365973E_280B_4A04_B419_EEE35B274D91
#define utility_HPP__C365973E_280B_4A04_B419_EEE35B274D91
//------------------------------------------------------------------------------
#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>

#include <llvm/ADT/StringRef.h>

#include <atomic>
#include <mutex>
#include <unordered_set>
//------------------------------------------------------------------------------

namespace clang
{
    class Preprocessor;
    class MacroDirective;
}

llvm::StringRef macroValueFromDirective(
    clang::Preprocessor const & preprocessor,
    llvm::StringRef const macroName,
    clang::MacroDirective const * def
);


struct SpinLockMutex : public std::atomic_flag
{
    SpinLockMutex() { clear( std::memory_order_relaxed ); }
};

struct SpinLock
{
    SpinLockMutex & mutex_;
    SpinLock( SpinLockMutex & mutex ) : mutex_( mutex )
    {
        while ( mutex_.test_and_set( std::memory_order_acquire ) );
    }

    ~SpinLock()
    {
        mutex_.clear( std::memory_order_release );
    }
};

template <typename T, typename Tag=T>
struct FlyweightStorage : public std::unordered_set<T>
{
public:
    const_iterator insert( T const & t )
    {
        {
            boost::shared_lock<boost::shared_mutex> const sharedLock( mutex_ );
            iterator result = find( t );
            if ( result != end() )
                return result;
        }
        boost::upgrade_lock<boost::shared_mutex> upgradeLock( mutex_ );
        iterator result = find( t );
        if ( result != end() )
            return result;
        boost::upgrade_to_unique_lock<boost::shared_mutex> const exclusiveLock( upgradeLock );
        return std::unordered_set<T>::insert( t ).first;
    }

    static FlyweightStorage & get() { return storage; }

private:
    boost::shared_mutex mutex_;
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

private:
    typename Storage::const_iterator iter_;
};

template<typename T, typename Tag>
bool operator<( Flyweight<T, Tag> const & a, Flyweight<T, Tag> const & b ) { return a.get() < b.get(); }

template<typename T, typename Tag>
bool operator==( Flyweight<T, Tag> const & a, Flyweight<T, Tag> const & b ) { return &a.get() == &b.get(); }


//------------------------------------------------------------------------------
#endif