//----------------------------------------------------------------------------
#pragma once
//----------------------------------------------------------------------------
#ifndef apiHooks_HPP__0966807F_833C_4FE1_B42A_F10CFE2FF1C0
#define apiHooks_HPP__0966807F_833C_4FE1_B42A_F10CFE2FF1C0
//----------------------------------------------------------------------------
#include "dllInject.hpp"

#include <MinHook.h>
#include <vector>

struct APIHookItem
{
    char const * const name;
    PROC replacement;
};

// struct APIHookDescription
// {
//     static char const * const moduleName;
// 
//     static APIHookItem const * const items;
//     static unsigned int const itemsCount;
//
//     typedef ... Data;
// };

template <typename Data>
struct APIHookHelper
{
    struct HookEntry
    {
        PROC replacement;
        PROC newOriginal;
    };
    typedef std::vector<HookEntry> HookList;

    HookList hookList_;
    Data data_;
    bool active_;

    APIHookHelper()
        :
        active_( false )
    {
        MH_Initialize();
    }

    template <typename APIHookDescription>
    void addAPIHook()
    {
        HMODULE const module = GetModuleHandle( APIHookDescription::moduleName );
        for ( unsigned int index( 0 ); index < APIHookDescription::itemsCount; ++index )
        {
            PROC original = GetProcAddress( module, APIHookDescription::items[ index ].name );
            PROC replacement = APIHookDescription::items[ index ].replacement;
            PROC newOriginal;
            MH_CreateHook( original, replacement, reinterpret_cast<void * *>( &newOriginal ) );
            HookEntry hookEntry = { replacement, newOriginal };
            hookList_.push_back( hookEntry );
        }
    }

    ~APIHookHelper()
    {
        active_ = false;
        MH_Uninitialize();
    }

    DWORD installHooks()
    {
        active_ = true;
        MH_EnableHook(MH_ALL_HOOKS);
        return 0;
    }

    DWORD removeHooks()
    {
        active_ = false;
        MH_DisableHook(MH_ALL_HOOKS);
        return 0;
    }

    PROC originalProc( PROC proc ) const
    {
        for ( unsigned int index( 0 ); index < hookList_.size(); ++index )
        {
            if ( proc == hookList_[ index ].replacement )
                return hookList_[ index ].newOriginal;
        }
        return proc;
    }

    bool active() const { return active_; }
    Data & data() { return data_; }
};

template <typename Derived, typename Data>
class APIHooks : public APIHookHelper<Data>
{
public:
    typedef Derived Derived;
    typedef Data Data;

protected:
    static Derived singleton;

public:
    static PROC original( PROC proc ) { return singleton.originalProc( proc ); }
    static bool isActive() { return singleton.active(); }
    static DWORD enable() { return singleton.installHooks(); }
    static DWORD disable() { return singleton.removeHooks(); }
    static Data & getData() { return singleton.data(); }
};

template <typename APIHookDescription, typename Data>
typename APIHooks<APIHookDescription, Data>::Derived APIHooks<APIHookDescription, Data>::singleton;


//----------------------------------------------------------------------------
#endif
//----------------------------------------------------------------------------
