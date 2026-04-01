/*
 * Copyright (c) 2026 ATrace Authors
 * SPDX-License-Identifier: MIT
 *
 * Enhanced dl_open / dl_sym implementation inspired by xDL (https://github.com/hexhacking/xDL).
 * Bypasses Android 7.0+ linker namespace restrictions by using dl_iterate_phdr
 * and in-memory ELF parsing with proper SYSV / GNU hash table lookups.
 */
#include "dl_utils.h"
#include "thread_utils.h"

#include <dlfcn.h>
#include <link.h>
#include <elf.h>
#include <inttypes.h>
#include <cstring>
#include <cstdlib>
#include <new>
#define ATRACE_LOG_TAG "DL"
#include "atrace_log.h"

namespace atrace {

namespace {

// ---------------------------------------------------------------------------
// DlHandle — opaque handle returned by dl_open()
// ---------------------------------------------------------------------------
struct DlHandle {
    char *pathname = nullptr;
    uintptr_t load_bias = 0;
    const ElfW(Phdr) *dlpi_phdr = nullptr;
    ElfW(Half) dlpi_phnum = 0;
    void *linker_handle = nullptr;

    bool dynsym_loaded = false;
    ElfW(Sym) *dynsym = nullptr;
    const char *dynstr = nullptr;

    struct {
        const uint32_t *buckets = nullptr;
        uint32_t buckets_cnt = 0;
        const uint32_t *chains = nullptr;
        uint32_t chains_cnt = 0;
    } sysv_hash;

    struct {
        const uint32_t *buckets = nullptr;
        uint32_t buckets_cnt = 0;
        const uint32_t *chains = nullptr;
        uint32_t symoffset = 0;
        const ElfW(Addr) *bloom = nullptr;
        uint32_t bloom_cnt = 0;
        uint32_t bloom_shift = 0;
    } gnu_hash;
};

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------
static bool str_ends_with(const char *str, const char *suffix) {
    size_t str_len = strlen(str);
    size_t suf_len = strlen(suffix);
    if (suf_len > str_len) return false;
    return strcmp(str + str_len - suf_len, suffix) == 0;
}

static void str_trim_ending(char *s) {
    char *end = s + strlen(s);
    while (end > s && (*(end - 1) == '\n' || *(end - 1) == '\r' || *(end - 1) == ' ')) {
        --end;
        *end = '\0';
    }
}

// ---------------------------------------------------------------------------
// dl_iterate_phdr-based library lookup (primary strategy)
// ---------------------------------------------------------------------------
struct FindLibCtx {
    DlHandle **out;
    const char *filename;
};

static int find_lib_cb(struct dl_phdr_info *info, size_t /*size*/, void *arg) {
    auto *ctx = static_cast<FindLibCtx *>(arg);

    if (info->dlpi_addr == 0 || !info->dlpi_name || info->dlpi_name[0] == '\0')
        return 0;

    const char *target = ctx->filename;
    const char *name = info->dlpi_name;

    bool match;
    if (target[0] == '/') {
        match = (name[0] == '/') ? (strcmp(name, target) == 0)
                                 : str_ends_with(target, name);
    } else {
        match = (name[0] == '/') ? str_ends_with(name, target)
                                 : (strcmp(name, target) == 0);
    }
    if (!match) return 0;

    auto *h = new(std::nothrow) DlHandle();
    if (!h) return 1;

    h->pathname = strdup(name);
    h->load_bias = info->dlpi_addr;
    h->dlpi_phdr = info->dlpi_phdr;
    h->dlpi_phnum = info->dlpi_phnum;

    *(ctx->out) = h;
    return 1;
}

static DlHandle *find_loaded_lib(const char *filename) {
    DlHandle *result = nullptr;
    FindLibCtx ctx{&result, filename};
    dl_iterate_phdr(find_lib_cb, &ctx);
    return result;
}

// ---------------------------------------------------------------------------
// /proc/self/maps fallback (for edge cases or very old Android)
// ---------------------------------------------------------------------------
static DlHandle *find_lib_from_maps(const char *filename) {
    FILE *fp = fopen("/proc/self/maps", "r");
    if (!fp) return nullptr;

    char line[1024];
    uintptr_t found_base = 0;
    char found_path[512] = {};

    while (fgets(line, sizeof(line), fp)) {
        if (!strstr(line, filename)) continue;

        uintptr_t start;
        if (sscanf(line, "%" SCNxPTR "-", &start) != 1) continue;

        char *path = strchr(line, '/');
        if (!path) continue;
        str_trim_ending(path);

        if (found_base == 0 || start < found_base) {
            found_base = start;
            snprintf(found_path, sizeof(found_path), "%s", path);
        }
    }
    fclose(fp);

    if (found_base == 0) return nullptr;
    if (memcmp(reinterpret_cast<void *>(found_base), ELFMAG, SELFMAG) != 0)
        return nullptr;

    auto *ehdr = reinterpret_cast<ElfW(Ehdr) *>(found_base);
    auto *phdr = reinterpret_cast<const ElfW(Phdr) *>(found_base + ehdr->e_phoff);

    uintptr_t min_vaddr = UINTPTR_MAX;
    for (int i = 0; i < ehdr->e_phnum; i++) {
        if (phdr[i].p_type == PT_LOAD && phdr[i].p_vaddr < min_vaddr)
            min_vaddr = phdr[i].p_vaddr;
    }
    if (min_vaddr == UINTPTR_MAX) return nullptr;

    auto *h = new(std::nothrow) DlHandle();
    if (!h) return nullptr;

    h->pathname = strdup(found_path);
    h->load_bias = found_base - min_vaddr;
    h->dlpi_phdr = phdr;
    h->dlpi_phnum = ehdr->e_phnum;
    return h;
}

// ---------------------------------------------------------------------------
// .dynsym loader — parses PT_DYNAMIC to populate hash tables
// ---------------------------------------------------------------------------
static bool load_dynsym(DlHandle *self) {
    if (self->dynsym_loaded) return self->dynsym != nullptr;
    self->dynsym_loaded = true;

    ElfW(Dyn) *dynamic = nullptr;
    for (size_t i = 0; i < self->dlpi_phnum; i++) {
        if (self->dlpi_phdr[i].p_type == PT_DYNAMIC) {
            dynamic = reinterpret_cast<ElfW(Dyn) *>(
                self->load_bias + self->dlpi_phdr[i].p_vaddr);
            break;
        }
    }
    if (!dynamic) return false;

    for (ElfW(Dyn) *d = dynamic; d->d_tag != DT_NULL; d++) {
        switch (d->d_tag) {
            case DT_SYMTAB:
                self->dynsym = reinterpret_cast<ElfW(Sym) *>(
                    self->load_bias + d->d_un.d_ptr);
                break;
            case DT_STRTAB:
                self->dynstr = reinterpret_cast<const char *>(
                    self->load_bias + d->d_un.d_ptr);
                break;
            case DT_HASH: {
                auto *raw = reinterpret_cast<const uint32_t *>(
                    self->load_bias + d->d_un.d_ptr);
                self->sysv_hash.buckets_cnt = raw[0];
                self->sysv_hash.chains_cnt  = raw[1];
                self->sysv_hash.buckets     = &raw[2];
                self->sysv_hash.chains      = &raw[2 + self->sysv_hash.buckets_cnt];
                break;
            }
            case DT_GNU_HASH: {
                auto *raw = reinterpret_cast<const uint32_t *>(
                    self->load_bias + d->d_un.d_ptr);
                self->gnu_hash.buckets_cnt  = raw[0];
                self->gnu_hash.symoffset    = raw[1];
                self->gnu_hash.bloom_cnt    = raw[2];
                self->gnu_hash.bloom_shift  = raw[3];
                self->gnu_hash.bloom   = reinterpret_cast<const ElfW(Addr) *>(&raw[4]);
                self->gnu_hash.buckets = reinterpret_cast<const uint32_t *>(
                    &self->gnu_hash.bloom[self->gnu_hash.bloom_cnt]);
                self->gnu_hash.chains  = &self->gnu_hash.buckets[self->gnu_hash.buckets_cnt];
                break;
            }
            default:
                break;
        }
    }

    if (!self->dynsym || !self->dynstr ||
        (self->sysv_hash.buckets_cnt == 0 && self->gnu_hash.buckets_cnt == 0)) {
        self->dynsym = nullptr;
        self->dynstr = nullptr;
        self->sysv_hash.buckets_cnt = 0;
        self->gnu_hash.buckets_cnt  = 0;
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// Hash functions
// ---------------------------------------------------------------------------
static uint32_t elf_sysv_hash(const char *name) {
    uint32_t h = 0, g;
    for (auto *p = reinterpret_cast<const uint8_t *>(name); *p; p++) {
        h = (h << 4) + *p;
        g = h & 0xf0000000;
        h ^= g;
        h ^= g >> 24;
    }
    return h;
}

static uint32_t elf_gnu_hash(const char *name) {
    uint32_t h = 5381;
    for (auto *p = reinterpret_cast<const uint8_t *>(name); *p; p++) {
        h += (h << 5) + *p;
    }
    return h;
}

// ---------------------------------------------------------------------------
// Symbol lookup via hash tables
// ---------------------------------------------------------------------------
static ElfW(Sym) *find_sym_sysv(DlHandle *self, const char *sym_name) {
    uint32_t hash = elf_sysv_hash(sym_name);
    for (uint32_t i = self->sysv_hash.buckets[hash % self->sysv_hash.buckets_cnt];
         i != 0;
         i = self->sysv_hash.chains[i]) {
        ElfW(Sym) *sym = &self->dynsym[i];
        if (strcmp(self->dynstr + sym->st_name, sym_name) == 0)
            return sym;
    }
    return nullptr;
}

static ElfW(Sym) *find_sym_gnu(DlHandle *self, const char *sym_name) {
    uint32_t hash = elf_gnu_hash(sym_name);

    constexpr uint32_t elfclass_bits = sizeof(ElfW(Addr)) * 8;
    auto word = self->gnu_hash.bloom[(hash / elfclass_bits) % self->gnu_hash.bloom_cnt];
    ElfW(Addr) mask =
        (static_cast<ElfW(Addr)>(1) << (hash % elfclass_bits)) |
        (static_cast<ElfW(Addr)>(1) << ((hash >> self->gnu_hash.bloom_shift) % elfclass_bits));

    if ((word & mask) != mask) return nullptr;

    uint32_t i = self->gnu_hash.buckets[hash % self->gnu_hash.buckets_cnt];
    if (i < self->gnu_hash.symoffset) return nullptr;

    for (;;) {
        ElfW(Sym) *sym = &self->dynsym[i];
        uint32_t chain_hash = self->gnu_hash.chains[i - self->gnu_hash.symoffset];

        if ((hash | 1u) == (chain_hash | 1u) &&
            strcmp(self->dynstr + sym->st_name, sym_name) == 0)
            return sym;

        if (chain_hash & 1u) break;
        i++;
    }
    return nullptr;
}

static void *find_dynsym(DlHandle *self, const char *symbol) {
    if (!load_dynsym(self)) return nullptr;

    ElfW(Sym) *sym = nullptr;

    if (self->gnu_hash.buckets_cnt > 0)
        sym = find_sym_gnu(self, symbol);

    if (!sym && self->sysv_hash.buckets_cnt > 0)
        sym = find_sym_sysv(self, symbol);

    if (!sym || sym->st_shndx == SHN_UNDEF)
        return nullptr;

    return reinterpret_cast<void *>(self->load_bias + sym->st_value);
}

} // anonymous namespace

// ===========================================================================
// Public API
// ===========================================================================

void *dl_open(const char *name) {
    if (!name) return nullptr;

    // 1) dl_iterate_phdr — works for already-loaded libs, bypasses namespace
    DlHandle *handle = find_loaded_lib(name);
    if (handle) {
        ALOGD("dl_open: found via dl_iterate_phdr: %s (bias %p)",
              name, reinterpret_cast<void *>(handle->load_bias));
        return handle;
    }

    // 2) dlopen — may work for whitelisted libs or API < 24
    void *linker_handle = dlopen(name, RTLD_NOW);
    if (linker_handle) {
        handle = find_loaded_lib(name);
        if (handle) {
            handle->linker_handle = linker_handle;
            ALOGD("dl_open: loaded via dlopen: %s", name);
            return handle;
        }
        dlclose(linker_handle);
    }

    // 3) /proc/self/maps fallback
    handle = find_lib_from_maps(name);
    if (handle) {
        ALOGD("dl_open: found via maps: %s (bias %p)",
              name, reinterpret_cast<void *>(handle->load_bias));
        return handle;
    }

    ALOGE("dl_open: failed to find library: %s", name);
    return nullptr;
}

void *dl_sym(void *handle, const char *symbol) {
    if (!handle || !symbol) return nullptr;

    auto *self = static_cast<DlHandle *>(handle);

    void *addr = find_dynsym(self, symbol);
    if (addr) return addr;

    if (self->linker_handle) {
        addr = dlsym(self->linker_handle, symbol);
        if (addr) return addr;
    }

    return nullptr;
}

void dl_close(void *handle) {
    if (!handle) return;

    auto *self = static_cast<DlHandle *>(handle);
    if (self->linker_handle)
        dlclose(self->linker_handle);
    free(self->pathname);
    delete self;
}

const char *dl_error() {
    return dlerror();
}

} // namespace atrace
