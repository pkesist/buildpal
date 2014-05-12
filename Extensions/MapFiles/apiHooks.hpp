//----------------------------------------------------------------------------
#pragma once
//----------------------------------------------------------------------------
#ifndef apiHooks_HPP__0966807F_833C_4FE1_B42A_F10CFE2FF1C0
#define apiHooks_HPP__0966807F_833C_4FE1_B42A_F10CFE2FF1C0
//----------------------------------------------------------------------------
#include "dllInject.hpp"

#include <vector>

struct APIHookDesc
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

// struct APIHookTraits
// {
//     static char const * const moduleName;
// 
//     static APIHookDesc const * const apiHookDesc;
//     static unsigned int const apiHookDescLen;
//
//     typedef ... Data;
// };

struct APIHookHelper
{
    typedef std::vector<PROC> ProcVector;
    ProcVector originals_;
    ProcVector replacements_;

    template <typename APIHookTraits>
    void addAPIHook()
    {
        HMODULE const module = GetModuleHandle( APIHookTraits::moduleName );
        for ( unsigned int index( 0 ); index < APIHookTraits::apiHookDescLen; ++index )
        {
            originals_.push_back( GetProcAddress( module, APIHookTraits::apiHookDesc[ index ].name ) );
            replacements_.push_back( APIHookTraits::apiHookDesc[ index ].replacement );
        }
    }

    DWORD installHooks() const
    {
        return hookWinAPI( originals_.data(), replacements_.data(), originals_.size() );
    }

    DWORD removeHooks() const
    {
        return hookWinAPI( replacements_.data(), originals_.data(), originals_.size() );
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
};


template <typename APIHookTraits>
class APIHooks : APIHookHelper
{
private:
    struct ImplicitHookTraits
    {
        static HMODULE WINAPI loadLibraryA( char * lpFileName );
        static HMODULE WINAPI loadLibraryW( wchar_t * lpFileName );
        static HMODULE WINAPI loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags );
        static HMODULE WINAPI loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags );
        static PROC WINAPI getProcAddress( HMODULE hModule, LPCSTR lpProcName );

        static char const moduleName[];
        static APIHookDesc const apiHookDesc[]; 
        static unsigned int const apiHookDescLen;
    };

public:
    typedef typename GetDataType<APIHookTraits>::type Data;

private:
    APIHooks()
    {
        addAPIHook<ImplicitHookTraits>();
        addAPIHook<APIHookTraits>();
    }

    Data data;
    static APIHooks singleton;

private:
    static PROC translate( PROC proc ) { return singleton.translateProc( proc ); }

public:
    static DWORD enable() { return singleton.installHooks(); }
    static DWORD disable() { return singleton.removeHooks(); }
    static Data & getData() { return singleton.data; }
};

template <typename APIHookTraits>
char const APIHooks<APIHookTraits>::ImplicitHookTraits::moduleName[] = "kernel32.dll";

template <typename APIHookTraits>
APIHookDesc const APIHooks<APIHookTraits>::ImplicitHookTraits::apiHookDesc[] = 
{
    { "LoadLibraryA"  , (PROC)loadLibraryA   },
    { "LoadLibraryW"  , (PROC)loadLibraryW   },
    { "LoadLibraryExA", (PROC)loadLibraryExA },
    { "LoadLibraryExW", (PROC)loadLibraryExW },
    { "GetProcAddress", (PROC)getProcAddress }
};

template <typename APIHookTraits>
APIHooks<APIHookTraits> APIHooks<APIHookTraits>::singleton;

template <typename APIHookTraits>
unsigned int const APIHooks<APIHookTraits>::ImplicitHookTraits::apiHookDescLen = sizeof(apiHookDesc) / sizeof(apiHookDesc[0]);

template <typename APIHookTraits>
HMODULE WINAPI APIHooks<APIHookTraits>::ImplicitHookTraits::loadLibraryA( char * lpFileName )
{
    HMODULE result = LoadLibraryA( lpFileName );
    APIHooks<APIHookTraits>::enable();
    return result;
}

template <typename APIHookTraits>
HMODULE WINAPI APIHooks<APIHookTraits>::ImplicitHookTraits::loadLibraryW( wchar_t * lpFileName )
{
    HMODULE result = LoadLibraryW( lpFileName );
    APIHooks<APIHookTraits>::enable();
    return result;
}

template <typename APIHookTraits>
HMODULE WINAPI APIHooks<APIHookTraits>::ImplicitHookTraits::loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags )
{
    HMODULE result = LoadLibraryExA( lpFileName, hFile, dwFlags );
    APIHooks<APIHookTraits>::enable();
    return result;
}

template <typename APIHookTraits>
HMODULE WINAPI APIHooks<APIHookTraits>::ImplicitHookTraits::loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags )
{
    HMODULE result = LoadLibraryExW( lpFileName, hFile, dwFlags );
    APIHooks<APIHookTraits>::enable();
    return result;
}

template <typename APIHookTraits>
PROC WINAPI APIHooks<APIHookTraits>::ImplicitHookTraits::getProcAddress( HMODULE hModule, LPCSTR lpProcName )
{
    return APIHooks<APIHookTraits>::translate( GetProcAddress( hModule, lpProcName ) ); 
}


//----------------------------------------------------------------------------
#endif
//----------------------------------------------------------------------------
