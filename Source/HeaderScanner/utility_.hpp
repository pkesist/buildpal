//------------------------------------------------------------------------------
#pragma once
//------------------------------------------------------------------------------
#ifndef utility_HPP__C365973E_280B_4A04_B419_EEE35B274D91
#define utility_HPP__C365973E_280B_4A04_B419_EEE35B274D91
//------------------------------------------------------------------------------
#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>
#include <boost/multi_index_container.hpp>
#include <boost/multi_index/hashed_index.hpp>
#include <boost/multi_index/mem_fun.hpp>

#include <boost/functional/hash_fwd.hpp>
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

class RefCount
{
private:
    RefCount & operator=( RefCount & );

public:
    RefCount( RefCount const & r ) : refCount( r.refCount.load() ), deleters( r.deleters ) {}
    RefCount() : refCount( 0 ), deleters( 0 ) {}

    void addRef() const
    {
        if ( refCount.fetch_add( 1, std::memory_order_relaxed ) == 0 )
            ++deleters;
    }

    bool decRef() const
    {
        return refCount.fetch_sub( 1, std::memory_order_relaxed ) == 1;
    }

    bool decDel() const
    {
        return --deleters == 0;
    }

    mutable std::atomic<std::size_t> refCount;
    mutable std::size_t deleters;
};

template<typename T>
struct Value
{
    Value( llvm::StringRef r ) : value( r ) {}

    llvm::StringRef str() const { return value.str(); }

    T value;
    RefCount refCount;
};

struct HashString
{
    inline std::size_t operator()( llvm::StringRef ref ) const
    {
        return boost::hash_range( ref.data(), ref.data() + ref.size() );
    }
};

template <typename T>
struct Container : public boost::multi_index::multi_index_container
<
    Value<T>,
    boost::multi_index::indexed_by
    <
        boost::multi_index::hashed_unique
        <
            boost::multi_index::const_mem_fun<Value<T>, llvm::StringRef, &Value<T>::str>,
            HashString
        >
    >
>
{};


template <typename T, typename Tag=T>
struct FlyweightStorage : public Container<T>
{
private: 
    typedef Container<T> Base;

public:
    Value<T> const * insert( llvm::StringRef s )
    {
        {
            boost::shared_lock<boost::shared_mutex> const sharedLock( mutex_ );
            iterator result = find( s );
            if ( result != end() )
            {
                result->refCount.addRef();
                return &*result;
            }
        }
        boost::upgrade_lock<boost::shared_mutex> upgradeLock( mutex_ );
        iterator result = find( s );
        if ( result != end() )
        {
            result->refCount.addRef();
            return &*result;
        }
        boost::upgrade_to_unique_lock<boost::shared_mutex> const exclusiveLock( upgradeLock );
        std::pair<iterator, bool> const res = Base::insert( Value<T>( s ) );
        assert( res.second );
        res.first->refCount.addRef();
        return &*res.first;
    }

    void remove( Value<T> const * value )
    {
        if ( value->refCount.decRef() )
        {
            boost::unique_lock<boost::shared_mutex> const lock( mutex_ );
            if ( value->refCount.decDel() )
                erase( iterator_to( *value ) );
        }
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

    Flyweight() : value_( 0 ) {}

    explicit Flyweight( llvm::StringRef s )
        : value_( Storage::get().insert( s ) )
    {}

    Flyweight( Flyweight && other )
        : value_( other.value_ )
    {
        other.value_ = 0;
    }

    Flyweight( Flyweight const & other )
        : value_( other.value_ )
    {
        value_->refCount.addRef();
    }

    ~Flyweight()
    {
        if ( value_ )
            Storage::get().remove( value_ );
    }

    Flyweight & operator=( Flyweight const & other )
    {
        if ( value_ )
            Storage::get().remove( value_ );
        value_ = other.value_;
        if ( value_ )
            value_->refCount.addRef();
        return *this;
    }

    T const & get() const { return value_->value; }

    operator T const & () const { return get(); }

    bool operator==( Flyweight<T, Tag> const & other ) const
    {
        return value_ == other.value_;
    }

private:
    Value<T> const * value_;
};


//------------------------------------------------------------------------------
#endif