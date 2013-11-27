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
#include <unordered_map>
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

class RefCount
{
private:
    RefCount( RefCount const & );
    RefCount & operator==( RefCount & );

public:
    RefCount( RefCount && r ) : refCount( r.refCount.load() ) {}
    RefCount() : refCount( 0 ) {}

    void addRef() const
    {
        refCount.fetch_add( 1, std::memory_order_relaxed );
    }

    void decRef() const
    {
        refCount.fetch_sub( 1, std::memory_order_relaxed );
    }

    std::size_t getRef() const
    {
        return refCount.load( std::memory_order_relaxed );
    }

    mutable std::atomic<std::size_t> refCount;
};

template <typename T, typename Tag=T>
struct FlyweightStorage : public std::unordered_map<T, RefCount>
{
private: 
    typedef std::unordered_map<T, RefCount> Base;

public:
    FlyweightStorage() : counter_( 0 ) {}

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
        std::pair<iterator, bool> const res = Base::insert( std::make_pair( t, RefCount() ) );
        res.first->second.addRef();
        counter_ += 1;
        if ( ( counter_ % 10240 ) == 0 )
        {
            const_iterator iter = begin();
            while ( iter != end() )
            {
                if ( iter->second.getRef() == 0 )
                    iter = Base::erase( iter );
                else
                    ++iter;
            }
            counter_ = 0;
        }
        return res.first;
    }

    static FlyweightStorage & get() { return storage; }

private:
    void cleanup( const_iterator iter )
    {
        boost::unique_lock<boost::shared_mutex> const exclusiveLock( mutex_ );
        Base::erase( iter );
    }

private:
    boost::shared_mutex mutex_;
    std::size_t counter_;
    static FlyweightStorage storage;
};

template <typename T, typename Tag>
FlyweightStorage<T, Tag> FlyweightStorage<T, Tag>::storage;

template<typename T, typename Tag=T>
struct Flyweight
{
    typedef FlyweightStorage<T, Tag> Storage;
    ~Flyweight()
    {
        iter_->second.decRef();
    }

    Flyweight( T const & t ) : iter_( Storage::get().insert( t ) )
    {
    }

    template<typename A1>
    Flyweight( A1 a1 ) : iter_( Storage::get().insert( T( a1 ) ) )
    {
    }

    template<typename A1, typename A2>
    Flyweight( A1 a1, A2 a2 ) : iter_( Storage::get().insert( T( a1, a2 ) ) )
    {
    }

    Flyweight( Flyweight const & other ) : iter_( other.iter_ )
    {
        iter_->second.addRef();
    }

    Flyweight & operator=( Flyweight const & other )
    {
        iter_->second.decRef();
        iter_ = other.iter_;
        iter_->second.addRef();
        return *this;
    }

    T const & get() const { return iter_->first; }
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