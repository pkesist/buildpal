//----------------------------------------------------------------------------
#pragma once
//----------------------------------------------------------------------------
#ifndef apiHooks_HPP__0966807F_833C_4FE1_B42A_F10CFE2FF1C0
#define apiHooks_HPP__0966807F_833C_4FE1_B42A_F10CFE2FF1C0
//----------------------------------------------------------------------------
#include "dllInject.hpp"

#include <vector>

struct APIHookItem
{
    char const * const name;
    PROC replacement;
};

template <typename T>
struct Helper { typedef void type; };

template <typename T, typename _ = typename Helper<T>::type>
struct GetDataType { struct type {}; };

template <typename T>
struct GetDataType<T, typename Helper<typename T::Data>::type>
{ typedef typename T::Data type; };

// struct APIHookDescription
// {
//     static char const * const moduleName;
// 
//     static APIHookItem const * const items;
//     static unsigned int const itemsCount;
//
//     typedef ... Data;
// };

struct APIHookHelper
{
    typedef std::vector<PROC> ProcVector;
    ProcVector originals_;
    ProcVector replacements_;
    // Implementation note:
    //   Ideally we wouldn't track whether hooks are active or not. When
    // inactive, our function pointers are removed from import tables and
    // shouldn't be called at all. However, a module can store a pointer
    // obtained by GetProcAddress() and call it whenever it wants.
    
    // Additionally, hook functions should be written to merely do the original
    // action if called when not active.
    bool active_;

    APIHookHelper() : active_( false ) {}

    template <typename APIHookDescription>
    void addAPIHook()
    {
        HMODULE const module = GetModuleHandle( APIHookDescription::moduleName );
        for ( unsigned int index( 0 ); index < APIHookDescription::itemsCount; ++index )
        {
            originals_.push_back( GetProcAddress( module, APIHookDescription::items[ index ].name ) );
            replacements_.push_back( APIHookDescription::items[ index ].replacement );
        }
    }

    ~APIHookHelper()
    {
        if ( active_ )
            removeHooks();
    }

    DWORD installHooks()
    {
        active_ = true;
        return hookWinAPI( originals_.data(), replacements_.data(), originals_.size() );
    }

    DWORD removeHooks()
    {
        active_ = false;
        return hookWinAPI( replacements_.data(), originals_.data(), originals_.size() );
    }

    PROC originalProc( PROC proc ) const
    {
        for ( unsigned int index( 0 ); index < originals_.size(); ++index )
        {
            if ( proc == replacements_[ index ] )
                return originals_[ index ];
        }
        return proc;
    }

    PROC translateProc( PROC proc ) const
    {
        for ( unsigned int index( 0 ); index < originals_.size(); ++index )
        {
            if ( proc == originals_[ index ] )
                return replacements_[ index ];
        }
        return proc;
    }

    bool active() const { return active_; }
};

template <typename Derived, typename Data>
class APIHooks : public APIHookHelper
{
public:
    typedef Data Data;
    typedef Derived Singleton;

private:
    struct LoadLibraryHooks
    {
        static HMODULE WINAPI loadLibraryA( char * lpFileName );
        static HMODULE WINAPI loadLibraryW( wchar_t * lpFileName );
        static HMODULE WINAPI loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags );
        static HMODULE WINAPI loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags );
        static PROC WINAPI getProcAddress( HMODULE, LPCSTR lpProcName );

        static char const moduleName[];
        static APIHookItem const items[]; 
        static unsigned int const itemsCount;
    };

protected:
    APIHooks()
    {
        addAPIHook<LoadLibraryHooks>();
    }

private:
    Data data;
    static Singleton singleton;

private:
    static PROC translate( PROC proc ) { return singleton.translateProc( proc ); }

public:
    static PROC original( PROC proc ) { return singleton.originalProc( proc ); }
    static bool isActive() { return singleton.active(); }
    static DWORD enable() { return singleton.installHooks(); }
    static DWORD disable() { return singleton.removeHooks(); }
    static Data & getData() { return singleton.data; }
};

template <typename APIHookDescription, typename Data>
char const APIHooks<APIHookDescription, Data>::LoadLibraryHooks::moduleName[] = "kernel32.dll";

template <typename APIHookDescription, typename Data>
APIHookItem const APIHooks<APIHookDescription, Data>::LoadLibraryHooks::items[] = 
{
    { "LoadLibraryA"  , (PROC)loadLibraryA   },
    { "LoadLibraryW"  , (PROC)loadLibraryW   },
    { "LoadLibraryExA", (PROC)loadLibraryExA },
    { "LoadLibraryExW", (PROC)loadLibraryExW },
    { "GetProcAddress", (PROC)getProcAddress }
};

template <typename APIHookDescription, typename Data>
typename APIHooks<APIHookDescription, Data>::Singleton APIHooks<APIHookDescription, Data>::singleton;

template <typename APIHookDescription, typename Data>
unsigned int const APIHooks<APIHookDescription, Data>::LoadLibraryHooks::itemsCount = sizeof(items) / sizeof(items[0]);

template <typename APIHookDescription, typename Data>
HMODULE WINAPI APIHooks<APIHookDescription, Data>::LoadLibraryHooks::loadLibraryA( char * lpFileName )
{
    HMODULE result = LoadLibraryA( lpFileName );
    if ( isActive() )
        APIHooks<APIHookDescription, Data>::enable();
    return result;
}

template <typename APIHookDescription, typename Data>
HMODULE WINAPI APIHooks<APIHookDescription, Data>::LoadLibraryHooks::loadLibraryW( wchar_t * lpFileName )
{
    HMODULE result = LoadLibraryW( lpFileName );
    if ( isActive() )
        APIHooks<APIHookDescription, Data>::enable();
    return result;
}

template <typename APIHookDescription, typename Data>
HMODULE WINAPI APIHooks<APIHookDescription, Data>::LoadLibraryHooks::loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags )
{
    HMODULE result = LoadLibraryExA( lpFileName, hFile, dwFlags );
    if ( isActive() )
        APIHooks<APIHookDescription, Data>::enable();
    return result;
}

template <typename APIHookDescription, typename Data>
HMODULE WINAPI APIHooks<APIHookDescription, Data>::LoadLibraryHooks::loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags )
{
    HMODULE result = LoadLibraryExW( lpFileName, hFile, dwFlags );
    if ( isActive() )
        APIHooks<APIHookDescription, Data>::enable();
    return result;
}

template <typename APIHookDescription, typename Data>
PROC WINAPI APIHooks<APIHookDescription, Data>::LoadLibraryHooks::getProcAddress( HMODULE hModule, LPCSTR lpProcName )
{
    PROC proc = GetProcAddress( hModule, lpProcName );
    return isActive() ? APIHooks<APIHookDescription, Data>::translate( proc ) : proc; 
}


//----------------------------------------------------------------------------
#endif
//----------------------------------------------------------------------------
