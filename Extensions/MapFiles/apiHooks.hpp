//----------------------------------------------------------------------------
#pragma once
//----------------------------------------------------------------------------
#ifndef apiHooks_HPP__0966807F_833C_4FE1_B42A_F10CFE2FF1C0
#define apiHooks_HPP__0966807F_833C_4FE1_B42A_F10CFE2FF1C0
//----------------------------------------------------------------------------
#include "dllInject.hpp"

struct APIHookDesc
{
    char const * const name;
    PROC replacement;
};

template <bool, typename T, typename F = void>
struct If { typedef T type; };

template<typename T, typename F>
struct If<false, T, F> { typedef F type; };

template <typename T, typename _ = void>
struct GetDataType { struct type {}; };

template <typename T>
struct GetDataType<T, typename If<false, typename T::Data>::type> { typedef typename T::Data type; };

// struct APIHookTraits
// {
//     static char const * const moduleName;
// 
//     static APIHookDesc const * const apiHookDesc;
//     static unsigned int const apiHookDescLen;
//
//     typedef ... Data;
// };

template<typename APIHookTraits>
struct APIHookHelper
{
    static unsigned int const procCount = APIHookTraits::apiHookDescLen;
    PROC originals_[procCount];
    PROC replacements_[procCount];

    APIHookHelper()
    {
        HMODULE module = GetModuleHandleA( APIHookTraits::moduleName );
        for ( unsigned int index( 0 ); index < procCount; ++index )
        {
            originals_[ index ] = GetProcAddress( module, APIHookTraits::apiHookDesc[ index ].name );
            replacements_[ index ] = APIHookTraits::apiHookDesc[ index ].replacement;
        }
    }

    DWORD installHooks() const
    {
        return hookWinAPI( originals_, replacements_, procCount );
    }

    DWORD removeHooks() const
    {
        return hookWinAPI( replacements_, originals_, procCount );
    }

    PROC translateProc( PROC proc ) const
    {
        for ( unsigned int index( 0 ); index < procCount; ++index )
        {
            if ( proc == originals_[ index ] )
                return replacements_[ index ];
        }
        return proc;
    }
};

template <typename APIHookTraits>
struct ImplicitHookTraits
{
    static HMODULE WINAPI loadLibraryA( char * lpFileName );
    static HMODULE WINAPI loadLibraryW( wchar_t * lpFileName );
    static HMODULE WINAPI loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags );
    static HMODULE WINAPI loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags );
    static PROC WINAPI getProcAddress( HMODULE hModule, LPCSTR lpProcName );

    static char const moduleName[];
    static APIHookDesc const apiHookDesc[]; 
    static unsigned int const apiHookDescLen = 5;
};

template <typename APIHookTraits>
char const ImplicitHookTraits<APIHookTraits>::moduleName[] = "kernel32.dll";

template <typename APIHookTraits>
APIHookDesc const ImplicitHookTraits<APIHookTraits>::apiHookDesc[] = 
{
    { "LoadLibraryA"  , (PROC)loadLibraryA   },
    { "LoadLibraryW"  , (PROC)loadLibraryW   },
    { "LoadLibraryExA", (PROC)loadLibraryExA },
    { "LoadLibraryExW", (PROC)loadLibraryExW },
    { "GetProcAddress", (PROC)getProcAddress }
};

template <typename APIHookTraits>
class APIHooks : APIHookHelper<APIHookTraits>, APIHookHelper<ImplicitHookTraits<APIHookTraits> >
{
public:
    typedef typename GetDataType<APIHookTraits>::type Data;

private:
    typedef APIHookHelper<APIHookTraits> Base;
    typedef APIHookHelper<ImplicitHookTraits<APIHookTraits> > ImplicitBase;

    APIHooks() {}

    Data data;
    static APIHooks singleton;

    DWORD installHooks() const
    {
        return Base::installHooks() + ImplicitBase::installHooks();
    }

    DWORD removeHooks() const
    {
        return Base::removeHooks() + ImplicitBase::removeHooks();
    }

    PROC translateProc( PROC proc ) const
    {
        return Base::translateProc( ImplicitBase::translateProc( proc ) );
    }

public:
    static DWORD enable() { return singleton.installHooks(); }
    static DWORD disable() { return singleton.removeHooks(); }
    static PROC translate( PROC proc ) { return singleton.translateProc( proc ); }
    static Data & getData() { return singleton.data; }
};

template <typename APIHookTraits>
APIHooks<APIHookTraits> APIHooks<APIHookTraits>::singleton;

template <typename APIHookTraits>
HMODULE WINAPI ImplicitHookTraits<APIHookTraits>::loadLibraryA( char * lpFileName )
{
    HMODULE result = LoadLibraryA( lpFileName );
    APIHooks<APIHookTraits>::enable();
    return result;
}

template <typename APIHookTraits>
HMODULE WINAPI ImplicitHookTraits<APIHookTraits>::loadLibraryW( wchar_t * lpFileName )
{
    HMODULE result = LoadLibraryW( lpFileName );
    APIHooks<APIHookTraits>::enable();
    return result;
}

template <typename APIHookTraits>
HMODULE WINAPI ImplicitHookTraits<APIHookTraits>::loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags )
{
    HMODULE result = LoadLibraryExA( lpFileName, hFile, dwFlags );
    APIHooks<APIHookTraits>::enable();
    return result;
}

template <typename APIHookTraits>
HMODULE WINAPI ImplicitHookTraits<APIHookTraits>::loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags )
{
    HMODULE result = LoadLibraryExW( lpFileName, hFile, dwFlags );
    APIHooks<APIHookTraits>::enable();
    return result;
}

template <typename APIHookTraits>
PROC WINAPI ImplicitHookTraits<APIHookTraits>::getProcAddress( HMODULE hModule, LPCSTR lpProcName )
{
    return APIHooks<APIHookTraits>::translate( GetProcAddress( hModule, lpProcName ) ); 
}


//----------------------------------------------------------------------------
#endif
//----------------------------------------------------------------------------
