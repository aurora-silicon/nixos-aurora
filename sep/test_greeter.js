// SPDX-License-Identifier: GPL-2.0-only
// Injected by test_greeter.py. Exercise GNOME's real reader-change/reset/service
// path with deterministic delayed replies, without accessing hardware or PAM.
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
class Emitter {
    constructor() { this.handlers = new Map(); }
    connect(name, callback) {
        const handlers = this.handlers.get(name) ?? [];
        handlers.push(callback);
        this.handlers.set(name, handlers);
    }
    connectObject(...args) {
        for (let i = 0; i < args.length - 1; i += 2) this.connect(args[i], args[i + 1]);
    }
    disconnectObject() {}
    emit(name, ...args) { for (const callback of this.handlers.get(name) ?? []) callback(this, ...args); }
}
class BusError extends Error {
    constructor(remote = 'net.reactivated.Fprint.Error.NoSuchDevice') { super(remote); this.remote = remote; }
    matches() { return false; }
}
const GObject = {
    Object: Emitter, properties: Symbol(), signals: Symbol(), TYPE_JSOBJECT: Object,
    ParamSpec: {uint() {}}, ParamFlags: {READWRITE: 1}, registerClass() {},
};
const GLib = {PRIORITY_DEFAULT: 0, Error: BusError};
let state;
class Proxy extends Emitter {
    constructor() { super(); this.g_name_owner = state.owner; this['scan-type'] = 'press'; state.proxies.push(this); }
    async init_async() {}
    async GetDefaultDeviceAsync() {
        state.queries++;
        const available = state.device;
        const barrier = state.barrier;
        state.barrier = null;
        if (barrier) await barrier;
        if (!available) throw new BusError();
        return ['/net/reactivated/Fprint/Device/0'];
    }
}
const Gio = {
    DBusProxy: Proxy, DBus: {system: {}}, DBusProxyFlags: {},
    DBusInterfaceInfo: {new_for_xml: name => ({name})}, FileMonitorFlags: {NONE: 0},
    File: {new_for_path: () => ({
        monitor_file() { state.monitor = new Emitter(); return state.monitor; },
        query_exists() { return state.marker; },
    })},
    IOErrorEnum: {CANCELLED: 1}, DBusError: {
        is_remote_error: e => e instanceof BusError, get_remote_error: e => e.remote,
    },
    Cancellable: class { cancel() {} is_cancelled() { return false; } },
    _promisify() {},
};
const loadInterfaceXML = name => name;
const logError = e => { throw e; };
const logErrorUnlessCancelled = e => { throw e; };
const Params = {parse: (params, defaults) => ({...defaults, ...params})};
const registerDestroyableType = () => {};
const InitError = class extends Error { constructor(cause) { super(cause.message); this.cause = cause; } };
const MessageType = {};
const Gdm = Object.fromEntries(['Client', 'UserVerifierProxy', 'UserVerifierChoiceListProxy', 'UserVerifierCustomJSONProxy'].map(name => [name, class {}]));
const _ = s => s;
const Settings = {PASSWORD_AUTHENTICATION_KEY: 'password', SMARTCARD_AUTHENTICATION_KEY: 'smartcard', FINGERPRINT_AUTHENTICATION_KEY: 'fingerprint'};
const SmartcardManager = {getSmartcardManager: () => new Emitter()};
const OVirt = {SERVICE_NAME: 'ovirt', getOVirtCredentialsManager: () => Object.assign(new Emitter(), {token: null})};
const Vmware = {SERVICE_NAME: 'vmware', getVmwareCredentialsManager: OVirt.getOVirtCredentialsManager};
function loadManager() {
@MANAGER@
    return {getFingerprintManager, FingerprintReaderType};
}
function loadAuth() {
@AUTH@
    return {AuthServices, Role, RoleProperties};
}
function loadLegacy(FingerprintManager, {AuthServices, Role, RoleProperties}) {
    const {FingerprintReaderType} = FingerprintManager;
@LEGACY@
    return AuthServicesLegacy;
}
class Verifier extends Emitter {
    get_connection() { return this; }
    async call_begin_verification_for_user(service) {
        if (service === 'gdm-fingerprint') {
            state.attempts++;
            if (!state.templates) throw new BusError('org.gnome.DisplayManager.SessionWorker.Error.ServiceUnavailable');
            state.verified++;
        }
    }
}
async function scenario({device = false, templates = false, marker = false, barrier = null} = {}) {
    state = {device, templates, marker, barrier, owner: ':1.2', queries: 0, attempts: 0, verified: 0, proxies: [], resets: []};
    const namespace = loadManager();
    const Legacy = loadLegacy(namespace, loadAuth());
    const auth = new Legacy({reauthOnly: false, settings: {get_boolean: key => key !== 'smartcard'}});
    // Use GNOME's actual beginVerification/_startServices/_canStartService and
    // clear/_updateEnabledMechanisms, with only the GDM endpoint substituted.
    auth._updateUserVerifier = () => { auth._userVerifier = new Verifier(); };
    auth.connect('reset', (_auth, options) => {
        state.resets.push(options);
        if (auth._userName) start(auth);
    });
    return {auth, manager: namespace.getFingerprintManager()};
}
function start(auth) {
    auth.clear();
    auth._selectedMechanism = auth._enabledMechanisms.find(m => m.serviceName === 'gdm-password');
    auth.beginVerification('fixture', {}).catch(e => {
        assert(e.cause instanceof BusError, `unexpected auth error ${e}`);
    });
}
function publish() { state.marker = true; state.monitor.emit('changed'); }
async function run() {
    // GDM is already accepting passwords when SEP eventually restores a reader.
    let {auth} = await scenario();
    await flush(); start(auth); await flush();
    assert(state.verified === 0 && state.attempts === 0, 'absent reader must not start fingerprint PAM');
    state.device = state.templates = true; publish(); await flush();
    assert(state.verified === 1, 'late reader must start fingerprint without restarting GDM');
    assert(state.resets.at(-1).reuseEntryText === true, 'late availability must preserve entry text');
    const queries = state.queries;
    state.monitor.emit('changed'); await flush();
    assert(state.queries === queries, 'duplicate file events must not reset authentication');

    // Critical case: the reader type is unchanged but PAM previously found no
    // enrolled fingers. Readiness must clear unavailable-services via reset.
    ({auth} = await scenario({device: true}));
    await flush(); start(auth); await flush();
    assert(auth._unavailableServices.has('gdm-fingerprint'), 'fixture must fail before templates');
    state.templates = true; publish(); await flush();
    assert(state.verified === 1 && !auth._unavailableServices.has('gdm-fingerprint'), 'same-type restore must retry PAM');

    // A completed restore before greeter startup must be picked up immediately.
    ({auth} = await scenario({device: true, templates: true, marker: true}));
    await flush(); start(auth); await flush();
    assert(state.verified === 1, 'initial restored reader must work');

    // A marker arriving while the initial D-Bus request is pending must cause
    // a fresh query after the stale response, rather than being lost.
    let release;
    const barrier = new Promise(resolve => { release = resolve; });
    ({auth} = await scenario({barrier}));
    await flush(); state.device = state.templates = true; publish(); release(); await flush();
    start(auth); await flush();
    assert(state.verified === 1, 'restore during pending query must work');

    // If the pending reply itself discovers the restored reader, its normal
    // change signal already resets authentication; don't force a second reset.
    const foundBarrier = new Promise(resolve => { release = resolve; });
    ({auth} = await scenario({device: true, barrier: foundBarrier}));
    await flush(); state.templates = true; publish(); release(); await flush();
    assert(state.resets.length === 1, 'a restore coalesced with discovery must reset once');
    start(auth); await flush();

    // Recover from daemon disappearance/reappearance without a second marker.
    state.device = false;
    const proxy = state.proxies[0];
    proxy.g_name_owner = null; proxy.emit('notify::g-name-owner'); await flush();
    state.device = true; proxy.g_name_owner = ':1.3'; proxy.emit('notify::g-name-owner'); await flush();
    assert(state.verified === 2, 'new fprintd owner must restore fingerprint authentication');

    ({auth} = await scenario());
    await flush(); publish(); await flush();
    const noReaderQueries = state.queries; await flush();
    assert(state.queries === noReaderQueries && state.attempts === 0, 'no reader must not poll or start fingerprint');
    printResult('PASS: late reader, same-type templates/PAM retry, early restore, in-flight restore, owner restart, duplicate events, no-reader idle');
}
const printResult = typeof print === 'function' ? print : console.log;
run().catch(e => { printResult(e.stack); throw e; });
