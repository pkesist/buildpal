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


template <typename APIHookDescription>
class APIHooks : APIHookHelper
{
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

public:
    typedef typename GetDataType<APIHookDescription>::type Data;

private:
    APIHooks()
    {
        addAPIHook<LoadLibraryHooks>();
        addAPIHook<APIHookDescription>();
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

template <typename APIHookDescription>
char const APIHooks<APIHookDescription>::LoadLibraryHooks::moduleName[] = "kernel32.dll";

template <typename APIHookDescription>
APIHookItem const APIHooks<APIHookDescription>::LoadLibraryHooks::items[] = 
{
    { "LoadLibraryA"  , (PROC)loadLibraryA   },
    { "LoadLibraryW"  , (PROC)loadLibraryW   },
    { "LoadLibraryExA", (PROC)loadLibraryExA },
    { "LoadLibraryExW", (PROC)loadLibraryExW },
    { "GetProcAddress", (PROC)getProcAddress }
};

template <typename APIHookDescription>
APIHooks<APIHookDescription> APIHooks<APIHookDescription>::singleton;

template <typename APIHookDescription>
unsigned int const APIHooks<APIHookDescription>::LoadLibraryHooks::itemsCount = sizeof(items) / sizeof(items[0]);

template <typename APIHookDescription>
HMODULE WINAPI APIHooks<APIHookDescription>::LoadLibraryHooks::loadLibraryA( char * lpFileName )
{
    HMODULE result = LoadLibraryA( lpFileName );
    APIHooks<APIHookDescription>::enable();
    return result;
}

template <typename APIHookDescription>
HMODULE WINAPI APIHooks<APIHookDescription>::LoadLibraryHooks::loadLibraryW( wchar_t * lpFileName )
{
    HMODULE result = LoadLibraryW( lpFileName );
    APIHooks<APIHookDescription>::enable();
    return result;
}

template <typename APIHookDescription>
HMODULE WINAPI APIHooks<APIHookDescription>::LoadLibraryHooks::loadLibraryExA( char * lpFileName, HANDLE hFile, DWORD dwFlags )
{
    HMODULE result = LoadLibraryExA( lpFileName, hFile, dwFlags );
    APIHooks<APIHookDescription>::enable();
    return result;
}

template <typename APIHookDescription>
HMODULE WINAPI APIHooks<APIHookDescription>::LoadLibraryHooks::loadLibraryExW( wchar_t * lpFileName, HANDLE hFile, DWORD dwFlags )
{
    HMODULE result = LoadLibraryExW( lpFileName, hFile, dwFlags );
    APIHooks<APIHookDescription>::enable();
    return result;
}

template <typename APIHookDescription>
PROC WINAPI APIHooks<APIHookDescription>::LoadLibraryHooks::getProcAddress( HMODULE hModule, LPCSTR lpProcName )
{
    return APIHooks<APIHookDescription>::translate( GetProcAddress( hModule, lpProcName ) ); 
}


//----------------------------------------------------------------------------
#endif
//----------------------------------------------------------------------------
