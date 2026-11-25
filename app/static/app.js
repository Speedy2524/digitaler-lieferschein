/**
 * Digitaler IT-Lieferschein – Frontend Application Logic (Alpine.js)
 */

// Fallback für <dialog closedby="any"> in Browsern ohne native closedBy-Unterstützung (Guide: dialog)
document.addEventListener("DOMContentLoaded", () => {
  if (typeof HTMLDialogElement !== "undefined" && !("closedBy" in HTMLDialogElement.prototype)) {
    const isOutside = (e, dialog) => {
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    for (const dialog of document.querySelectorAll('dialog[closedby="any"]')) {
      let pressedOutside = false;
      dialog.addEventListener("pointerdown", (e) => {
        pressedOutside = isOutside(e, dialog);
      });
      dialog.addEventListener("pointerup", (e) => {
        if (pressedOutside && isOutside(e, dialog)) {
          dialog.close();
        }
      });
    }
  }
});

function deliveryApp() {
  return {
    // Design-Theme: 'erp' | 'business' | 'gmuend' | 'standard'
    uiTheme: localStorage.getItem("it_ls_ui_theme") || "erp",

    // Navigation: 'deliveries' | 'prepare' | 'handover' | 'archive' | 'admin' | 'settings'
    activeTab: "deliveries",
    isLoading: false,
    isSubmitting: false,

    // Ausgewählter Lieferschein im ERP-Split-View (rechts)
    selectedSplitNote: null,

    // App- & Auth-Status
    needsSetup: false,
    authEnabled: true,
    authenticated: false,
    currentUser: null,

    // Login-Modus: 'password' (Benutzername + Passwort) | 'pin' (Schnell-PIN)
    loginMode: "password",
    loginUsername: localStorage.getItem("it_ls_last_username") || "",
    loginPin: "",
    loginError: "",

    // Optionaler Admin-Login bei deaktivierter globaler Anmeldung
    adminLoginUsername: localStorage.getItem("it_ls_last_username") || "",
    adminLoginSecret: "",
    adminLoginError: "",

    // Ersteinrichtungs-Formular (Initiales Admin-Konto)
    setupError: "",
    setupForm: {
      username: "admin",
      full_name: "",
      email: "",
      password: "",
      pin: "",
      add_to_staff_list: true,
    },

    // System-Metadaten (Header & Sidebar)
    appTitle: "Digitaler IT-Lieferschein",
    departmentName: "Stadtverwaltung – Schul-IT",
    departmentSubtitle: "",
    departmentContact: "",
    smtpEnabled: false,
    smtpHost: "",
    osticketConfigured: false,
    osticketEmail: "",

    // Toast-Benachrichtigungen
    toast: {
      visible: false,
      type: "success", // 'success' | 'error' | 'info'
      title: "",
      message: "",
    },

    // Dashboard-Zähler
    stats: {
      draft: 0,
      ready: 0,
      completed: 0,
      email_errors: 0,
    },

    // Stammdaten
    schools: [],
    staffList: [],

    // Lokale Benutzerverwaltung
    usersList: [],
    userFormError: "",
    userForm: {
      id: null,
      username: "",
      full_name: "",
      email: "",
      role: "staff",
      password: "",
      pin: "",
      clear_pin: false,
      active: true,
      add_to_staff_list: true,
    },

    // Konfigmenü (Systemeinstellungen in DB)
    settingsForm: {
      app_title: "Digitaler IT-Lieferschein",
      department_name: "Stadtverwaltung – Schul-IT / Amt für Bildung und Sport",
      department_subtitle: "Kommunale IT-Betreuung der Schulen",
      department_contact: "",
      auth_enabled: true,
      smtp_enabled: false,
      smtp_host: "",
      smtp_port: 587,
      smtp_security: "starttls",
      smtp_username: "",
      smtp_password: "",
      smtp_password_set: false,
      smtp_from_email: "",
      smtp_from_name: "Schul-IT Lieferschein-System",
      osticket_enabled: false,
      osticket_email: "",
      global_archive_cc_email: "",
    },
    testEmailRecipient: "",
    isTestingSmtp: false,

    // Lieferschein-Listen
    openNotes: [], // Status BEREIT
    draftAndReadyNotes: [], // Status ENTWURF + BEREIT
    archivedNotes: [], // Status ABGESCHLOSSEN

    // Suchbegriffe
    searchOpen: "",
    searchArchive: "",

    // Stufe 1: Formular "Vorbereiten / Neu" (und "Direkt-Übergabe")
    directHandoverMode: false,
    formError: "",
    form: {
      id: null,
      delivery_number: null,
      school_id: "",
      school_name: "",
      recipient_email: "",
      cc_email: "",
      osticket_number: "",
      ordered_by: "",
      room: "",
      notes: "",
      status: "BEREIT",
      items: [
        {
          device_type: "",
          inventory_number: "",
          serial_number: "",
          supplier: "",
          invoice_number: "",
          quantity: 1,
        },
      ],
    },

    // Stufe 2: Übergabe & Unterschrift vor Ort
    currentHandoverNote: null,
    handoverForm: {
      delivered_by_select: "",
      delivered_by_custom: "",
      received_by: "",
      handover_notes: "",
    },
    handoverError: "",
    signaturePad: null,
    signatureResizeBound: false,
    completedResultNote: null,

    // Archiv-Detailansicht
    selectedArchiveNote: null,
    resendingEmailId: null,

    // Barcode-Scanner (ZXing-WASM + iPad Foto-Fallback)
    zxingConfigured: false,
    scannerStream: null,
    scannerTrack: null,
    scannerCanvas: null,
    scannerTimerId: null,
    scannerDecoding: false,
    scannerStarting: false,
    scannerActive: false,
    scannerPaused: false,
    scannerCameras: [],
    scannerSelectedCameraId: localStorage.getItem("it_ls_camera_id") || "",
    scannerCapabilities: { zoom: null, torch: false },
    scannerZoom: 1,
    scannerZoomOptions: [1, 1.5, 2, 3],
    scannerTorchOn: false,
    scannerCandidates: [],
    scannerPhotoLoading: false,
    scannerTarget: { rowIndex: 0, field: "inventory_number" },
    scannerError: "",
    scannerManualCode: "",

    // Serien- / Bulk-Erfassung (z. B. 40 iPads auf einmal oder Excel/CSV-Import)
    bulkError: "",
    bulkForm: {
      mode: "range", // 'range' | 'import'
      device_type: "",
      supplier: "",
      invoice_number: "",
      start_inventory: "",
      end_inventory: "",
      count: 10,
      serial_lines: "",
      import_text: "",
      single_col_type: "serial_with_start", // 'serial_with_start' | 'inventory_only'
      replace_empty_rows: true,
    },

    // Admin: Schule & Mitarbeiter Formulare
    schoolForm: {
      id: null,
      name: "",
      short_code: "",
      email: "",
      cc_email: "",
      address: "",
      active: true,
    },
    staffForm: {
      id: null,
      name: "",
      role: "",
      email: "",
      active: true,
    },

    async init() {
      this.applyTheme(this.uiTheme);
      this.configureZxingWasm();
      await this.checkAuthStatus();
      if (this.authenticated && !this.needsSetup) {
        await this.loadInitialData();
      }
    },

    setUiTheme(themeName) {
      this.uiTheme = themeName;
      localStorage.setItem("it_ls_ui_theme", themeName);
      this.applyTheme(themeName);
    },

    applyTheme(themeName) {
      document.documentElement.setAttribute("data-ui-theme", themeName);
    },

    showToast(title, message = "", type = "success") {
      this.toast = { visible: true, title, message, type };
      setTimeout(() => {
        this.toast.visible = false;
      }, 4800);
    },

    getCookie(name) {
      const prefix = `${name}=`;
      const parts = document.cookie ? document.cookie.split(";") : [];
      for (const part of parts) {
        const trimmed = part.trim();
        if (trimmed.startsWith(prefix)) {
          return decodeURIComponent(trimmed.slice(prefix.length));
        }
      }
      return "";
    },

    async apiFetch(url, options = {}) {
      const method = (options.method || "GET").toUpperCase();
      const headers = Object.assign(
        { "Content-Type": "application/json" },
        options.headers || {}
      );
      if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
        const csrfToken = this.getCookie("it_ls_csrf");
        if (csrfToken) {
          headers["X-CSRF-Token"] = csrfToken;
        }
      }
      const response = await fetch(url, {
        ...options,
        headers,
        credentials: "same-origin",
      });
      if (response.status === 401) {
        this.authenticated = false;
        this.currentUser = null;
        throw new Error("Sitzung abgelaufen oder Anmeldung erforderlich.");
      }
      const contentType = response.headers.get("content-type") || "";
      let data = null;
      if (contentType.includes("application/json")) {
        data = await response.json();
      } else {
        data = await response.text();
      }
      if (!response.ok) {
        let msg = "Ein Fehler ist aufgetreten.";
        if (data && typeof data === "object") {
          if (typeof data.detail === "string") {
            msg = data.detail;
          } else if (Array.isArray(data.detail)) {
            msg = data.detail.map((e) => e.msg || JSON.stringify(e)).join(" | ");
          }
        }
        throw new Error(msg);
      }
      return data;
    },

    async checkAuthStatus() {
      try {
        localStorage.removeItem("it_ls_token");
        const res = await fetch("/api/auth/status", {
          credentials: "same-origin",
        });
        const data = await res.json();
        this.needsSetup = Boolean(data.needs_setup);
        this.authEnabled = Boolean(data.auth_enabled);
        this.authenticated = Boolean(data.authenticated);
        this.currentUser = data.current_user || null;

        this.appTitle = data.app_title || this.appTitle;
        this.departmentName = data.department_name || this.departmentName;
        this.departmentSubtitle = data.department_subtitle || "";
        this.departmentContact = data.department_contact || "";
        this.smtpEnabled = Boolean(data.smtp_enabled);
        this.smtpHost = data.smtp_host || "";
        this.osticketConfigured = Boolean(data.osticket_configured);
        this.osticketEmail = data.osticket_email || "";
      } catch (err) {
        console.error("Auth-Status konnte nicht geprüft werden:", err);
      }
    },

    async submitInitialSetup() {
      this.setupError = "";
      if (!this.setupForm.username.trim() || !this.setupForm.full_name.trim()) {
        this.setupError = "Bitte Benutzername und vollständigen Namen eingeben.";
        return;
      }
      if (!this.setupForm.password || this.setupForm.password.trim().length < 8) {
        this.setupError = "Das Passwort muss mindestens 8 Zeichen lang sein.";
        return;
      }
      if (this.setupForm.pin && this.setupForm.pin.trim() && this.setupForm.pin.trim().length < 4) {
        this.setupError = "Die Schnell-PIN muss mindestens 4 Zeichen lang sein.";
        return;
      }
      this.isSubmitting = true;
      try {
        const res = await fetch("/api/auth/setup", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.setupForm),
        });
        const data = await res.json();
        if (!res.ok) {
          this.setupError = data.detail || "Ersteinrichtung fehlgeschlagen.";
          return;
        }
        this.currentUser = data.user;
        this.needsSetup = false;
        this.authenticated = true;
        if (data.user && data.user.username) {
          localStorage.setItem("it_ls_last_username", data.user.username);
          this.loginUsername = data.user.username;
          this.adminLoginUsername = data.user.username;
        }
        this.showToast(
          "Ersteinrichtung abgeschlossen",
          `Willkommen, ${data.user.full_name}!`,
          "success"
        );
        await this.checkAuthStatus();
        await this.loadInitialData();
      } catch (err) {
        this.setupError = err.message || "Verbindungsfehler.";
      } finally {
        this.isSubmitting = false;
      }
    },

    async submitLogin() {
      this.loginError = "";
      const uname = this.loginUsername ? this.loginUsername.trim() : "";
      const payload = {
        username: uname || null,
        pin_or_password: this.loginPin,
      };
      if (!payload.username) {
        this.loginError = "Bitte geben Sie Ihren Benutzernamen ein.";
        return;
      }
      if (!payload.pin_or_password) {
        this.loginError = "Bitte Passwort bzw. Schnell-PIN eingeben.";
        return;
      }

      this.isSubmitting = true;
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          this.loginError = data.detail || "Anmeldung fehlgeschlagen.";
          return;
        }
        localStorage.setItem("it_ls_last_username", data.user?.username || uname);
        this.authenticated = true;
        this.currentUser = data.user || null;
        this.loginPin = "";
        this.showToast(
          "Angemeldet",
          this.currentUser ? `Angemeldet als ${this.currentUser.full_name}` : "Erfolgreich angemeldet.",
          "success"
        );
        await this.checkAuthStatus();
        await this.loadInitialData();
      } catch (err) {
        this.loginError = err.message || "Verbindungsfehler.";
      } finally {
        this.isSubmitting = false;
      }
    },

    openAdminLoginModal() {
      this.adminLoginError = "";
      this.adminLoginSecret = "";
      const dlg = document.getElementById("admin-login-dialog");
      if (dlg && !dlg.open) {
        dlg.showModal();
      }
    },

    closeAdminLoginModal() {
      const dlg = document.getElementById("admin-login-dialog");
      if (dlg && dlg.open) {
        dlg.close();
      }
    },

    async submitAdminLogin() {
      this.adminLoginError = "";
      const uname = this.adminLoginUsername ? this.adminLoginUsername.trim() : "";
      if (!uname || !this.adminLoginSecret) {
        this.adminLoginError = "Bitte Benutzername und Passwort/PIN eingeben.";
        return;
      }
      this.isSubmitting = true;
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: uname, pin_or_password: this.adminLoginSecret }),
        });
        const data = await res.json();
        if (!res.ok) {
          this.adminLoginError = data.detail || "Anmeldung fehlgeschlagen.";
          return;
        }
        localStorage.setItem("it_ls_last_username", data.user?.username || uname);
        this.authenticated = true;
        this.currentUser = data.user || null;
        this.adminLoginSecret = "";
        this.closeAdminLoginModal();
        await this.checkAuthStatus();
        if (this.currentUser && this.currentUser.role === "admin") {
          this.switchTab("settings");
        }
        this.showToast("Administrator angemeldet", this.currentUser?.full_name || uname, "success");
      } catch (err) {
        this.adminLoginError = err.message || "Verbindungsfehler.";
      } finally {
        this.isSubmitting = false;
      }
    },

    async logout() {
      const csrfToken = this.getCookie("it_ls_csrf");
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
      });
      localStorage.removeItem("it_ls_token");
      this.currentUser = null;
      this.authenticated = false;
      this.activeTab = "deliveries";
      this.selectedSplitNote = null;
      this.currentHandoverNote = null;
      this.completedResultNote = null;
      this.selectedArchiveNote = null;
      this.openNotes = [];
      this.draftAndReadyNotes = [];
      this.archivedNotes = [];
      this.usersList = [];
      this.schools = [];
      this.staffList = [];
      this.stats = { draft: 0, ready: 0, completed: 0, email_errors: 0 };
      this.resetPrepareForm(false);
      this.resetSchoolForm();
      this.resetStaffForm();
      this.resetUserForm();
      this.settingsForm.smtp_password = "";
      this.settingsForm.smtp_password_set = false;
      this.settingsForm.smtp_host = "";
      this.settingsForm.smtp_username = "";
      this.settingsForm.osticket_email = "";
      this.settingsForm.global_archive_cc_email = "";
      await this.checkAuthStatus();
    },

    async loadInitialData() {
      this.isLoading = true;
      try {
        const promises = [
          this.loadStats(),
          this.loadSchools(),
          this.loadStaff(),
          this.loadOpenNotes(),
          this.loadDraftAndReadyNotes(),
          this.loadArchivedNotes(),
        ];
        if (this.currentUser && this.currentUser.role === "admin") {
          promises.push(this.loadUsers(), this.loadSystemSettings());
        }
        await Promise.all(promises);
      } catch (err) {
        this.showToast("Fehler beim Laden", err.message, "error");
      } finally {
        this.isLoading = false;
      }
    },

    async loadStats() {
      this.stats = await this.apiFetch("/api/stats");
    },

    async loadSchools() {
      this.schools = await this.apiFetch("/api/schools");
    },

    async loadStaff() {
      this.staffList = await this.apiFetch("/api/staff");
    },

    async loadOpenNotes() {
      const q = encodeURIComponent(this.searchOpen.trim());
      this.openNotes = await this.apiFetch(`/api/delivery-notes?status=BEREIT&search=${q}`);
      if (this.openNotes.length > 0) {
        const stillExists =
          this.selectedSplitNote &&
          this.openNotes.find((n) => n.id === this.selectedSplitNote.id);
        this.selectedSplitNote = stillExists || this.openNotes[0];
      } else {
        this.selectedSplitNote = null;
      }
    },

    async loadDraftAndReadyNotes() {
      this.draftAndReadyNotes = await this.apiFetch("/api/delivery-notes?status=ENTWURF,BEREIT");
    },

    async loadArchivedNotes() {
      const q = encodeURIComponent(this.searchArchive.trim());
      this.archivedNotes = await this.apiFetch(`/api/delivery-notes?status=ABGESCHLOSSEN&search=${q}`);
    },

    switchTab(tab) {
      this.activeTab = tab;
      if (tab === "deliveries") {
        this.loadOpenNotes();
        this.loadStats();
      } else if (tab === "prepare") {
        this.loadDraftAndReadyNotes();
      } else if (tab === "archive") {
        this.loadArchivedNotes();
        this.loadStats();
      } else if (tab === "admin") {
        this.loadSchools();
        this.loadStaff();
      } else if (tab === "settings") {
        if (!this.currentUser || this.currentUser.role !== "admin") {
          this.activeTab = "deliveries";
          this.openAdminLoginModal();
          return;
        }
        this.loadUsers();
        this.loadSystemSettings();
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    },

    // =========================================================================
    // Lokale Benutzerverwaltung (/api/users)
    // =========================================================================

    async loadUsers() {
      try {
        this.usersList = await this.apiFetch("/api/users");
      } catch (err) {
        console.warn("Benutzerliste nicht geladen:", err.message);
      }
    },

    resetUserForm() {
      this.userFormError = "";
      this.userForm = {
        id: null,
        username: "",
        full_name: "",
        email: "",
        role: "staff",
        password: "",
        pin: "",
        clear_pin: false,
        active: true,
        add_to_staff_list: true,
      };
    },

    editUser(u) {
      this.userFormError = "";
      this.userForm = {
        id: u.id,
        username: u.username,
        full_name: u.full_name,
        email: u.email || "",
        role: u.role,
        password: "",
        pin: "",
        clear_pin: false,
        active: u.active,
        add_to_staff_list: false,
      };
    },

    async saveUser() {
      this.userFormError = "";
      if (!this.userForm.username.trim() || !this.userForm.full_name.trim()) {
        this.userFormError = "Benutzername und vollständiger Name sind Pflichtfelder.";
        return;
      }
      const pwTrim = this.userForm.password ? this.userForm.password.trim() : "";
      const pinTrim = this.userForm.pin ? this.userForm.pin.trim() : "";
      const hasPw = pwTrim.length > 0;
      const hasPin = pinTrim.length > 0;
      if (!this.userForm.id && !hasPw && !hasPin) {
        this.userFormError = "Bitte vergeben Sie ein Passwort oder eine Schnell-PIN (oder beides).";
        return;
      }
      if (hasPw && pwTrim.length < 8) {
        this.userFormError = "Das Passwort muss mindestens 8 Zeichen lang sein.";
        return;
      }
      if (hasPin && pinTrim.length < 4) {
        this.userFormError = "Die Schnell-PIN muss mindestens 4 Zeichen lang sein.";
        return;
      }

      try {
        if (this.userForm.id) {
          await this.apiFetch(`/api/users/${this.userForm.id}`, {
            method: "PUT",
            body: JSON.stringify({
              username: this.userForm.username.trim(),
              full_name: this.userForm.full_name.trim(),
              email: this.userForm.email ? this.userForm.email.trim() : null,
              role: this.userForm.role,
              password: this.userForm.password ? this.userForm.password : null,
              pin: this.userForm.pin ? this.userForm.pin : null,
              clear_pin: Boolean(this.userForm.clear_pin),
              active: Boolean(this.userForm.active),
            }),
          });
          this.showToast("Benutzer aktualisiert", this.userForm.full_name, "success");
        } else {
          await this.apiFetch("/api/users", {
            method: "POST",
            body: JSON.stringify({
              username: this.userForm.username.trim(),
              full_name: this.userForm.full_name.trim(),
              email: this.userForm.email ? this.userForm.email.trim() : null,
              role: this.userForm.role,
              password: this.userForm.password,
              pin: this.userForm.pin ? this.userForm.pin : null,
              active: Boolean(this.userForm.active),
              add_to_staff_list: Boolean(this.userForm.add_to_staff_list),
            }),
          });
          this.showToast("Benutzer angelegt", this.userForm.full_name, "success");
        }
        this.resetUserForm();
        await Promise.all([this.loadUsers(), this.loadStaff(), this.checkAuthStatus()]);
      } catch (err) {
        this.userFormError = err.message;
      }
    },

    async deleteUser(u) {
      if (!confirm(`Benutzerkonto "${u.full_name}" (${u.username}) wirklich löschen?`)) {
        return;
      }
      try {
        await this.apiFetch(`/api/users/${u.id}`, { method: "DELETE" });
        this.showToast("Benutzer gelöscht", u.username, "info");
        await this.loadUsers();
      } catch (err) {
        this.showToast("Löschen nicht möglich", err.message, "error");
      }
    },

    // =========================================================================
    // Konfigmenü / Systemeinstellungen (/api/settings)
    // =========================================================================

    async loadSystemSettings() {
      try {
        const data = await this.apiFetch("/api/settings");
        this.settingsForm = {
          app_title: data.app_title || "Digitaler IT-Lieferschein",
          department_name: data.department_name || "",
          department_subtitle: data.department_subtitle || "",
          department_contact: data.department_contact || "",
          auth_enabled: Boolean(data.auth_enabled),
          smtp_enabled: Boolean(data.smtp_enabled),
          smtp_host: data.smtp_host || "",
          smtp_port: Number(data.smtp_port) || 587,
          smtp_security: data.smtp_security || "starttls",
          smtp_username: data.smtp_username || "",
          smtp_password: "",
          smtp_password_set: Boolean(data.smtp_password_set),
          smtp_from_email: data.smtp_from_email || "",
          smtp_from_name: data.smtp_from_name || "Schul-IT Lieferschein-System",
          osticket_enabled: Boolean(data.osticket_enabled),
          osticket_email: data.osticket_email || "",
          global_archive_cc_email: data.global_archive_cc_email || "",
        };
        if (!this.testEmailRecipient && this.currentUser && this.currentUser.email) {
          this.testEmailRecipient = this.currentUser.email;
        }
      } catch (err) {
        console.warn("Systemeinstellungen konnten nicht geladen werden:", err.message);
      }
    },

    async saveSystemSettings() {
      this.isSubmitting = true;
      try {
        const payload = {
          app_title: this.settingsForm.app_title,
          department_name: this.settingsForm.department_name,
          department_subtitle: this.settingsForm.department_subtitle,
          department_contact: this.settingsForm.department_contact,
          auth_enabled: Boolean(this.settingsForm.auth_enabled),
          smtp_enabled: Boolean(this.settingsForm.smtp_enabled),
          smtp_host: this.settingsForm.smtp_host,
          smtp_port: Number(this.settingsForm.smtp_port) || 587,
          smtp_security: this.settingsForm.smtp_security,
          smtp_username: this.settingsForm.smtp_username,
          smtp_password:
            this.settingsForm.smtp_password && this.settingsForm.smtp_password.trim() !== ""
              ? this.settingsForm.smtp_password
              : "__UNCHANGED__",
          smtp_from_email: this.settingsForm.smtp_from_email,
          smtp_from_name: this.settingsForm.smtp_from_name,
          osticket_enabled: Boolean(this.settingsForm.osticket_enabled),
          osticket_email: this.settingsForm.osticket_email,
          global_archive_cc_email: this.settingsForm.global_archive_cc_email,
        };

        await this.apiFetch("/api/settings", {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        await Promise.all([this.loadSystemSettings(), this.checkAuthStatus()]);
        this.showToast(
          "Konfiguration gespeichert",
          "Alle Systemeinstellungen wurden dauerhaft in der Datenbank übernommen.",
          "success"
        );
      } catch (err) {
        this.showToast("Fehler beim Speichern", err.message, "error");
      } finally {
        this.isSubmitting = false;
      }
    },

    async sendSmtpTestMail() {
      if (!this.testEmailRecipient || !this.testEmailRecipient.includes("@")) {
        this.showToast("Empfänger fehlt", "Bitte eine gültige E-Mail-Adresse für die Testmail eingeben.", "error");
        return;
      }
      // Vor dem Test aktuelle Eingaben speichern
      await this.saveSystemSettings();
      this.isTestingSmtp = true;
      try {
        const res = await this.apiFetch("/api/settings/test-smtp", {
          method: "POST",
          body: JSON.stringify({ recipient_email: this.testEmailRecipient.trim() }),
        });
        this.showToast("SMTP-Test erfolgreich", res.message, "success");
      } catch (err) {
        this.showToast("SMTP-Test fehlgeschlagen", err.message, "error");
      } finally {
        this.isTestingSmtp = false;
      }
    },

    // =========================================================================
    // Stufe 1: Lieferschein vorbereiten / bearbeiten / Direkt-Übergabe
    // =========================================================================

    resetPrepareForm(directMode = false) {
      this.directHandoverMode = directMode;
      this.formError = "";
      this.form = {
        id: null,
        delivery_number: null,
        school_id: "",
        school_name: "",
        recipient_email: "",
        cc_email: "",
        osticket_number: "",
        ordered_by: "",
        room: "",
        notes: "",
        status: "BEREIT",
        items: [
          {
            device_type: "",
            inventory_number: "",
            serial_number: "",
            supplier: "",
            invoice_number: "",
            quantity: 1,
          },
        ],
      };
    },

    startNewPrepare() {
      this.resetPrepareForm(false);
      this.switchTab("prepare");
    },

    startDirectHandover() {
      this.resetPrepareForm(true);
      this.switchTab("prepare");
    },

    onSchoolChange() {
      const sid = Number(this.form.school_id);
      const found = this.schools.find((s) => s.id === sid);
      if (found) {
        this.form.school_name = found.name;
        this.form.recipient_email = found.email || "";
        this.form.cc_email = found.cc_email || "";
      }
    },

    sanitizeOsticketInput() {
      if (!this.form.osticket_number) return;
      this.form.osticket_number = this.form.osticket_number.replace(/[^\d]/g, "");
    },

    addItemRow(focusIndex = null) {
      this.form.items.push({
        device_type: "",
        inventory_number: "",
        serial_number: "",
        supplier: "",
        invoice_number: "",
        quantity: 1,
      });
      this.$nextTick(() => {
        const idx = focusIndex !== null ? focusIndex : this.form.items.length - 1;
        const el = document.getElementById(`item-type-${idx}`);
        if (el) el.focus();
      });
    },

    duplicateItemTypeFromAbove(index) {
      if (index > 0 && this.form.items[index - 1]) {
        const prev = this.form.items[index - 1];
        this.form.items[index].device_type = prev.device_type;
        this.form.items[index].supplier = prev.supplier || "";
        this.form.items[index].invoice_number = prev.invoice_number || "";
        this.$nextTick(() => {
          const invInput = document.getElementById(`item-inv-${index}`);
          if (invInput) invInput.focus();
        });
      }
    },

    removeItemRow(index) {
      if (this.form.items.length <= 1) {
        this.form.items[0] = {
          device_type: "",
          inventory_number: "",
          serial_number: "",
          supplier: "",
          invoice_number: "",
          quantity: 1,
        };
        return;
      }
      this.form.items.splice(index, 1);
    },

    handleScannerEnter(event, index, field) {
      if (event.isComposing || event.keyCode === 229) {
        return;
      }
      event.preventDefault();

      if (field === "device_type") {
        const inv = document.getElementById(`item-inv-${index}`);
        if (inv) inv.focus();
      } else if (field === "inventory_number") {
        const sn = document.getElementById(`item-sn-${index}`);
        if (sn) sn.focus();
      } else if (field === "serial_number") {
        if (index === this.form.items.length - 1) {
          const current = this.form.items[index];
          this.form.items.push({
            device_type: current.device_type,
            inventory_number: "",
            serial_number: "",
            supplier: current.supplier || "",
            invoice_number: current.invoice_number || "",
            quantity: 1,
          });
          this.$nextTick(() => {
            const nextIndex = index + 1;
            const targetId = current.device_type ? `item-inv-${nextIndex}` : `item-type-${nextIndex}`;
            const nextEl = document.getElementById(targetId);
            if (nextEl) nextEl.focus();
          });
        } else {
          const nextIdx = index + 1;
          const nextItem = this.form.items[nextIdx];
          // Wenn Inventarnummer schon z. B. per Bulk-Generator befüllt ist, direkt zur nächsten Seriennummer springen
          const targetId =
            nextItem && nextItem.inventory_number && nextItem.inventory_number.trim()
              ? `item-sn-${nextIdx}`
              : `item-inv-${nextIdx}`;
          const nextEl = document.getElementById(targetId);
          if (nextEl) nextEl.focus();
        }
      }
    },

    // =========================================================================
    // Serien- / Bulk-Erfassung (Nummernreihe + Copy&Paste / CSV-Import)
    // =========================================================================

    parseInventoryToken(raw) {
      const cleaned = (raw || "").trim();
      const m = cleaned.match(/^(.*?)(\d+)$/);
      if (!m) return null;
      return {
        prefix: m[1],
        num: parseInt(m[2], 10),
        width: m[2].length,
      };
    },

    formatInventoryNumber(parsed, offset) {
      const value = parsed.num + offset;
      return `${parsed.prefix}${String(value).padStart(parsed.width, "0")}`;
    },

    onBulkStartOrCountChange() {
      const startParsed = this.parseInventoryToken(this.bulkForm.start_inventory);
      const count = Math.max(1, Math.min(500, parseInt(this.bulkForm.count, 10) || 1));
      if (startParsed) {
        this.bulkForm.end_inventory = this.formatInventoryNumber(startParsed, count - 1);
      }
    },

    onBulkEndInventoryChange() {
      const startParsed = this.parseInventoryToken(this.bulkForm.start_inventory);
      const endParsed = this.parseInventoryToken(this.bulkForm.end_inventory);
      if (startParsed && endParsed && startParsed.prefix === endParsed.prefix && endParsed.num >= startParsed.num) {
        const diff = endParsed.num - startParsed.num + 1;
        if (diff <= 500) {
          this.bulkForm.count = diff;
        }
      }
    },

    buildBulkPreviewItems() {
      const deviceType = (this.bulkForm.device_type || "").trim();
      const supplier = (this.bulkForm.supplier || "").trim();
      const invoice = (this.bulkForm.invoice_number || "").trim();

      if (!deviceType) {
        return { error: "Bitte zuerst eine Gerätebezeichnung / Typ angeben.", items: [] };
      }

      if (this.bulkForm.mode === "range") {
        const startParsed = this.parseInventoryToken(this.bulkForm.start_inventory);
        if (!startParsed) {
          return {
            error: "Bitte eine Start-Inventarnummer mit Ziffern am Ende eingeben (z. B. EDV-00120).",
            items: [],
          };
        }

        let count = parseInt(this.bulkForm.count, 10);
        const endRaw = (this.bulkForm.end_inventory || "").trim();
        if (endRaw) {
          const endParsed = this.parseInventoryToken(endRaw);
          if (!endParsed || endParsed.prefix !== startParsed.prefix || endParsed.num < startParsed.num) {
            return {
              error: `Bis-Inventarnummer muss mit „${startParsed.prefix}“ beginnen und >= Startnummer sein.`,
              items: [],
            };
          }
          count = endParsed.num - startParsed.num + 1;
        }

        if (!Number.isInteger(count) || count < 1 || count > 500) {
          return { error: "Bitte eine gültige Stückzahl zwischen 1 und 500 angeben.", items: [] };
        }

        const serials = (this.bulkForm.serial_lines || "")
          .split(/\r?\n/)
          .map((s) => s.trim())
          .filter((s) => s.length > 0);

        const items = [];
        for (let i = 0; i < count; i++) {
          items.push({
            device_type: deviceType,
            inventory_number: this.formatInventoryNumber(startParsed, i),
            serial_number: serials[i] || "",
            supplier,
            invoice_number: invoice,
            quantity: 1,
          });
        }
        return { error: "", items };
      }

      // Modus: 'import' (Excel / CSV / Scanner-Liste)
      const lines = (this.bulkForm.import_text || "")
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter((l) => l.length > 0);

      if (lines.length === 0) {
        return { error: "Bitte mindestens eine Zeile in das Importfeld einfügen.", items: [] };
      }
      if (lines.length > 500) {
        return { error: "Maximal 500 Positionen pro Import möglich.", items: [] };
      }

      const startParsed =
        this.bulkForm.single_col_type === "serial_with_start"
          ? this.parseInventoryToken(this.bulkForm.start_inventory)
          : null;

      const items = [];
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const parts = line
          .split(/\t|;|,/)
          .map((p) => p.trim())
          .filter((p, idx) => idx < 2 || p.length > 0);

        if (parts.length >= 2 && parts[0] && parts[1]) {
          items.push({
            device_type: deviceType,
            inventory_number: parts[0],
            serial_number: parts[1],
            supplier,
            invoice_number: invoice,
            quantity: 1,
          });
        } else {
          const val = parts[0] || line;
          if (this.bulkForm.single_col_type === "serial_with_start") {
            if (!startParsed) {
              return {
                error:
                  "Für einspaltige Seriennummern bitte oben eine Start-Inventarnummer (z. B. EDV-00120) angeben oder 2 Spalten (Inventarnummer;Seriennummer) einfügen.",
                items: [],
              };
            }
            items.push({
              device_type: deviceType,
              inventory_number: this.formatInventoryNumber(startParsed, i),
              serial_number: val,
              supplier,
              invoice_number: invoice,
              quantity: 1,
            });
          } else {
            items.push({
              device_type: deviceType,
              inventory_number: val,
              serial_number: "",
              supplier,
              invoice_number: invoice,
              quantity: 1,
            });
          }
        }
      }
      return { error: "", items };
    },

    getBulkPreviewSummary() {
      if (!this.bulkForm.device_type.trim()) {
        return { valid: false, error: "", count: 0, sample: [] };
      }
      const res = this.buildBulkPreviewItems();
      return {
        valid: !res.error && res.items.length > 0,
        error: res.error,
        count: res.items.length,
        sample: res.items.slice(0, 3),
        last: res.items.length > 3 ? res.items[res.items.length - 1] : null,
      };
    },

    openBulkItemsModal() {
      this.bulkError = "";
      const refItem =
        this.form.items.find((i) => i.device_type.trim() || i.supplier?.trim() || i.invoice_number?.trim()) ||
        this.form.items[0];
      if (!this.bulkForm.device_type && refItem?.device_type) {
        this.bulkForm.device_type = refItem.device_type;
      }
      if (!this.bulkForm.supplier && refItem?.supplier) {
        this.bulkForm.supplier = refItem.supplier;
      }
      if (!this.bulkForm.invoice_number && refItem?.invoice_number) {
        this.bulkForm.invoice_number = refItem.invoice_number;
      }
      if (this.bulkForm.start_inventory && !this.bulkForm.end_inventory) {
        this.onBulkStartOrCountChange();
      }
      const dlg = document.getElementById("bulk-items-dialog");
      if (dlg && !dlg.open) {
        dlg.showModal();
      }
    },

    closeBulkItemsModal() {
      const dlg = document.getElementById("bulk-items-dialog");
      if (dlg && dlg.open) {
        dlg.close();
      }
    },

    applyBulkItems() {
      this.bulkError = "";
      const res = this.buildBulkPreviewItems();
      if (res.error) {
        this.bulkError = res.error;
        return;
      }
      if (res.items.length === 0) {
        this.bulkError = "Es konnten keine Positionen erzeugt werden.";
        return;
      }

      const startOffset = this.bulkForm.replace_empty_rows
        ? this.form.items.filter(
            (i) => i.device_type.trim() !== "" || i.inventory_number.trim() !== "" || (i.serial_number && i.serial_number.trim() !== "")
          )
        : [...this.form.items];

      const firstNewIndex = startOffset.length;
      this.form.items = startOffset.concat(res.items);

      this.closeBulkItemsModal();
      this.showToast(
        `${res.items.length} Positionen übernommen`,
        res.items.some((i) => !i.serial_number)
          ? "Die Inventarnummern sind befüllt – Sie können jetzt nacheinander alle Seriennummern scannen."
          : "Alle Inventar- und Seriennummern wurden eingetragen.",
        "success"
      );

      const firstMissingSnIdx = this.form.items.findIndex(
        (i, idx) => idx >= firstNewIndex && (!i.serial_number || !i.serial_number.trim())
      );
      if (firstMissingSnIdx !== -1) {
        this.$nextTick(() => {
          const el = document.getElementById(`item-sn-${firstMissingSnIdx}`);
          if (el) el.focus();
        });
      }
    },

    editExistingNote(note) {
      this.directHandoverMode = false;
      this.formError = "";
      this.form = {
        id: note.id,
        delivery_number: note.delivery_number,
        school_id: note.school_id || "",
        school_name: note.school_name || "",
        recipient_email: note.recipient_email || "",
        cc_email: note.cc_email || "",
        osticket_number: note.osticket_number || "",
        ordered_by: note.ordered_by || "",
        room: note.room || "",
        notes: note.notes || "",
        status: note.status === "ENTWURF" ? "ENTWURF" : "BEREIT",
        items:
          note.items && note.items.length > 0
            ? note.items.map((i) => ({
                device_type: i.device_type,
                inventory_number: i.inventory_number,
                serial_number: i.serial_number || "",
                supplier: i.supplier || note.supplier || "",
                invoice_number: i.invoice_number || note.invoice_number || "",
                quantity: i.quantity || 1,
              }))
            : [
                {
                  device_type: "",
                  inventory_number: "",
                  serial_number: "",
                  supplier: "",
                  invoice_number: "",
                  quantity: 1,
                },
              ],
      };
      this.switchTab("prepare");
    },

    async saveDeliveryNote(targetStatus, proceedToHandover = false) {
      this.formError = "";
      this.sanitizeOsticketInput();

      if (!this.form.school_id && !this.form.school_name.trim()) {
        this.formError = "Bitte wählen Sie eine Schule aus.";
        return;
      }
      if (!this.form.recipient_email || !this.form.recipient_email.includes("@")) {
        this.formError = "Bitte geben Sie eine gültige E-Mail-Adresse des Schulsekretariats an.";
        return;
      }

      const validItems = this.form.items.filter(
        (i) => i.device_type.trim() !== "" || i.inventory_number.trim() !== ""
      );
      if (validItems.length === 0) {
        this.formError = "Bitte fügen Sie mindestens eine Geräteposition mit Bezeichnung und Inventarnummer hinzu.";
        return;
      }
      for (let idx = 0; idx < validItems.length; idx++) {
        if (!validItems[idx].device_type.trim() || !validItems[idx].inventory_number.trim()) {
          this.formError = `Position ${idx + 1}: Gerätebezeichnung und Inventarnummer sind Pflichtfelder.`;
          return;
        }
        const qty = Number(validItems[idx].quantity);
        if (!Number.isInteger(qty) || qty < 1 || qty > 9999) {
          this.formError = `Position ${idx + 1}: Die Menge muss zwischen 1 und 9999 liegen.`;
          return;
        }
      }

      this.isSubmitting = true;
      try {
        const payload = {
          school_id: this.form.school_id ? Number(this.form.school_id) : null,
          school_name: this.form.school_name,
          recipient_email: this.form.recipient_email.trim(),
          cc_email: this.form.cc_email ? this.form.cc_email.trim() : null,
          osticket_number: this.form.osticket_number ? this.form.osticket_number.trim() : null,
          ordered_by: this.form.ordered_by,
          room: this.form.room,
          notes: this.form.notes,
          status: targetStatus,
          items: validItems.map((i) => ({
            device_type: i.device_type.trim(),
            inventory_number: i.inventory_number.trim(),
            serial_number: i.serial_number ? i.serial_number.trim() : null,
            supplier: i.supplier ? i.supplier.trim() : null,
            invoice_number: i.invoice_number ? i.invoice_number.trim() : null,
            quantity: Number(i.quantity),
          })),
        };

        let savedNote;
        if (this.form.id) {
          savedNote = await this.apiFetch(`/api/delivery-notes/${this.form.id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
        } else {
          savedNote = await this.apiFetch("/api/delivery-notes", {
            method: "POST",
            body: JSON.stringify(payload),
          });
        }

        await Promise.all([
          this.loadStats(),
          this.loadOpenNotes(),
          this.loadDraftAndReadyNotes(),
        ]);

        if (proceedToHandover || this.directHandoverMode) {
          this.resetPrepareForm(false);
          this.openHandoverView(savedNote);
          return;
        }

        const statusLabel =
          targetStatus === "ENTWURF"
            ? "als Entwurf gespeichert"
            : "zur Auslieferung freigegeben";
        this.showToast(
          `Lieferschein ${savedNote.delivery_number}`,
          `Erfolgreich ${statusLabel}.`,
          "success"
        );
        this.resetPrepareForm(false);
        if (targetStatus === "BEREIT") {
          this.switchTab("deliveries");
        }
      } catch (err) {
        this.formError = err.message;
      } finally {
        this.isSubmitting = false;
      }
    },

    async deleteNote(note) {
      if (!confirm(`Möchten Sie den Lieferschein ${note.delivery_number} (${note.school_name}) wirklich löschen?`)) {
        return;
      }
      try {
        await this.apiFetch(`/api/delivery-notes/${note.id}`, { method: "DELETE" });
        this.showToast("Gelöscht", `Lieferschein ${note.delivery_number} wurde entfernt.`, "info");
        if (this.form.id === note.id) {
          this.resetPrepareForm(false);
        }
        await Promise.all([
          this.loadStats(),
          this.loadOpenNotes(),
          this.loadDraftAndReadyNotes(),
        ]);
      } catch (err) {
        this.showToast("Fehler beim Löschen", err.message, "error");
      }
    },

    // =========================================================================
    // Kamera-Barcode-Scanner (ZXing-WASM + iPadOS Safari & Foto-Scan Fallback)
    // =========================================================================

    configureZxingWasm() {
      if (this.zxingConfigured || typeof ZXingWASM === "undefined") return;
      if (typeof ZXingWASM.setZXingModuleOverrides === "function") {
        ZXingWASM.setZXingModuleOverrides({
          locateFile: (file) =>
            file.endsWith(".wasm")
              ? "/static/vendor/zxing_reader.wasm?v=20261125-7"
              : `/static/vendor/${file}`,
        });
      }
      this.zxingConfigured = true;
    },

    _formatCameraError(err) {
      const name = err?.name || "";
      const rawMsg = err?.message ? ` (${err.message})` : "";
      if (!window.isSecureContext) {
        return "Kamerazugriff erfordert eine sichere HTTPS-Verbindung. Bitte nutzen Sie „Foto-Scan (Kamera-App)“ oder geben Sie den Code manuell ein.";
      }
      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        return "Kamerazugriff wurde verweigert. Bitte unter iPad-Einstellungen → Safari → Kamera für diese Seite erlauben oder unten „Foto-Scan (Kamera-App)“ nutzen.";
      }
      if (name === "NotFoundError" || name === "DevicesNotFoundError") {
        return "Keine Kamera gefunden. Bitte nutzen Sie „Foto-Scan (Kamera-App)“ oder geben Sie den Code manuell ein.";
      }
      if (name === "NotReadableError" || name === "TrackStartError") {
        return "Die Kamera wird derzeit von einer anderen App blockiert. Bitte kurz schließen oder unten „Foto-Scan“ nutzen.";
      }
      return `Live-Kamera konnte nicht gestartet werden${rawMsg}. Alternativ funktioniert unten jederzeit „Foto-Scan (Kamera-App)“.`;
    },

    _extractUniqueBarcodes(results) {
      const seen = new Set();
      const unique = [];
      for (const res of results || []) {
        if (!res || res.isValid === false || !res.text) continue;
        const text = String(res.text).trim();
        if (!text || seen.has(text)) continue;
        seen.add(text);
        unique.push({
          text,
          format: res.format || "Barcode",
        });
      }
      return unique;
    },

    async openBarcodeScanner(rowIndex, field) {
      this.scannerTarget = { rowIndex, field };
      this.scannerError = "";
      this.scannerManualCode = "";
      this.scannerCandidates = [];
      this.scannerPaused = false;
      this.scannerCapabilities = { zoom: null, torch: false };
      this.scannerTorchOn = false;
      this.configureZxingWasm();

      const dlg = document.getElementById("scanner-dialog");
      if (dlg && !dlg.open) {
        dlg.showModal();
      }

      if (typeof ZXingWASM === "undefined") {
        this.scannerError =
          "Barcode-Decoder nicht geladen. Bitte Code unten manuell eingeben.";
        return;
      }

      if (typeof ZXingWASM.prepareZXingModule === "function") {
        ZXingWASM.prepareZXingModule({ fireImmediately: true }).catch(() => {});
      }

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        this.scannerError = this._formatCameraError(null);
        return;
      }

      await this.startCameraStream();
    },

    async startCameraStream(explicitDeviceId = null) {
      this.stopBarcodeScanner();
      this.scannerStarting = true;
      this.scannerError = "";
      this.scannerCandidates = [];
      this.scannerPaused = false;

      const preferredId = explicitDeviceId || this.scannerSelectedCameraId;
      const attempts = [];
      if (preferredId) {
        attempts.push({
          video: {
            deviceId: { exact: preferredId },
            width: { ideal: 1920, min: 640 },
            height: { ideal: 1080, min: 480 },
          },
          audio: false,
        });
      }
      attempts.push(
        {
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920, min: 640 },
            height: { ideal: 1080, min: 480 },
          },
          audio: false,
        },
        {
          video: { facingMode: "environment" },
          audio: false,
        },
        { video: true, audio: false }
      );

      let stream = null;
      let lastErr = null;
      for (let i = 0; i < attempts.length; i++) {
        try {
          stream = await navigator.mediaDevices.getUserMedia(attempts[i]);
          if (preferredId && i > 0) {
            this.scannerSelectedCameraId = "";
            localStorage.removeItem("it_ls_camera_id");
          }
          break;
        } catch (err) {
          lastErr = err;
          if (err?.name === "NotAllowedError" || err?.name === "PermissionDeniedError") {
            break;
          }
        }
      }

      if (!stream) {
        this.scannerStarting = false;
        this.scannerActive = false;
        this.scannerError = this._formatCameraError(lastErr);
        return;
      }

      const dlg = document.getElementById("scanner-dialog");
      const videoEl = document.getElementById("scanner-video");
      if (!dlg || !dlg.open || !videoEl) {
        stream.getTracks().forEach((t) => t.stop());
        this.scannerStarting = false;
        return;
      }

      this.scannerStream = stream;
      this.scannerTrack = stream.getVideoTracks()[0] || null;
      videoEl.setAttribute("playsinline", "true");
      videoEl.muted = true;
      videoEl.srcObject = stream;

      try {
        await videoEl.play();
      } catch (err) {
        // Safari spielt oft automatisch sobald Metadaten da sind
      }

      this.scannerStarting = false;
      this.scannerActive = true;

      await this.refreshScannerCameras();
      await this.configureTrackCapabilities();
      this.scheduleScannerTick();
    },

    async refreshScannerCameras() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        this.scannerCameras = devices
          .filter((d) => d.kind === "videoinput")
          .map((d, idx) => ({
            deviceId: d.deviceId,
            label: d.label || `Kamera ${idx + 1}`,
          }));
        const activeId = this.scannerTrack?.getSettings?.().deviceId;
        if (activeId) {
          this.scannerSelectedCameraId = activeId;
        }
      } catch (e) {
        this.scannerCameras = [];
      }
    },

    async configureTrackCapabilities() {
      if (!this.scannerTrack || typeof this.scannerTrack.getCapabilities !== "function") {
        this.scannerCapabilities = { zoom: null, torch: false };
        return;
      }
      try {
        const caps = this.scannerTrack.getCapabilities() || {};
        const zoomCaps = caps.zoom && typeof caps.zoom.max === "number" ? caps.zoom : null;
        this.scannerCapabilities = {
          zoom: zoomCaps,
          torch: Boolean(caps.torch),
        };

        const advanced = {};
        if (caps.focusMode && Array.isArray(caps.focusMode) && caps.focusMode.includes("continuous")) {
          advanced.focusMode = "continuous";
        }
        if (zoomCaps) {
          const minZ = zoomCaps.min ?? 1;
          const maxZ = zoomCaps.max ?? 1;
          const candidates = [1, 1.5, 2, 2.5, 3].filter((z) => z >= minZ && z <= maxZ);
          if (!candidates.includes(minZ)) candidates.unshift(Number(minZ.toFixed(1)));
          this.scannerZoomOptions = candidates;

          const defaultZoom = maxZ >= 1.5 && minZ <= 1.0 ? 1.5 : minZ;
          this.scannerZoom = defaultZoom;
          if (defaultZoom !== minZ) {
            advanced.zoom = defaultZoom;
          }
        }
        if (Object.keys(advanced).length > 0 && typeof this.scannerTrack.applyConstraints === "function") {
          await this.scannerTrack.applyConstraints({ advanced: [advanced] });
        }
      } catch (e) {
        // Safari/iOS ignoriert nicht unterstützte Track-Constraints gefahrlos
      }
    },

    async switchScannerCamera() {
      if (!this.scannerSelectedCameraId) return;
      localStorage.setItem("it_ls_camera_id", this.scannerSelectedCameraId);
      await this.startCameraStream(this.scannerSelectedCameraId);
    },

    async applyScannerZoom() {
      if (!this.scannerTrack || !this.scannerCapabilities.zoom) return;
      try {
        await this.scannerTrack.applyConstraints({
          advanced: [{ zoom: Number(this.scannerZoom) }],
        });
      } catch (e) {
        // ignore unsupported zoom steps
      }
    },

    async toggleScannerTorch() {
      if (!this.scannerTrack || !this.scannerCapabilities.torch) return;
      const next = !this.scannerTorchOn;
      try {
        await this.scannerTrack.applyConstraints({
          advanced: [{ torch: next }],
        });
        this.scannerTorchOn = next;
      } catch (e) {
        // ignore
      }
    },

    async refocusScannerCamera() {
      if (!this.scannerTrack || typeof this.scannerTrack.applyConstraints !== "function") return;
      try {
        const caps = this.scannerTrack.getCapabilities ? this.scannerTrack.getCapabilities() : {};
        if (caps.focusMode && caps.focusMode.includes("single-shot")) {
          await this.scannerTrack.applyConstraints({ advanced: [{ focusMode: "single-shot" }] });
          setTimeout(() => {
            if (this.scannerTrack && caps.focusMode.includes("continuous")) {
              this.scannerTrack.applyConstraints({ advanced: [{ focusMode: "continuous" }] }).catch(() => {});
            }
          }, 400);
        }
      } catch (e) {
        // ignore
      }
    },

    scheduleScannerTick() {
      if (!this.scannerActive || this.scannerPaused) return;
      this.scannerTimerId = setTimeout(async () => {
        await this.decodeCurrentVideoFrame();
        if (this.scannerActive && !this.scannerPaused) {
          this.scheduleScannerTick();
        }
      }, 110);
    },

    async decodeCurrentVideoFrame() {
      if (!this.scannerActive || this.scannerPaused || this.scannerDecoding) return;
      const videoEl = document.getElementById("scanner-video");
      if (!videoEl || videoEl.readyState < 2 || !videoEl.videoWidth || !videoEl.videoHeight) return;

      this.scannerDecoding = true;
      try {
        if (!this.scannerCanvas) {
          this.scannerCanvas = document.createElement("canvas");
        }
        const scale = videoEl.videoWidth > 1600 ? 1600 / videoEl.videoWidth : 1;
        const width = Math.max(1, Math.round(videoEl.videoWidth * scale));
        const height = Math.max(1, Math.round(videoEl.videoHeight * scale));
        if (this.scannerCanvas.width !== width) this.scannerCanvas.width = width;
        if (this.scannerCanvas.height !== height) this.scannerCanvas.height = height;

        const ctx = this.scannerCanvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(videoEl, 0, 0, width, height);
        const imgData = ctx.getImageData(0, 0, width, height);

        const results = await ZXingWASM.readBarcodes(imgData, {
          tryHarder: true,
          tryRotate: true,
          tryInvert: true,
          tryDownscale: true,
          maxNumberOfSymbols: 4,
        });
        const unique = this._extractUniqueBarcodes(results);
        if (unique.length === 1) {
          this.applyScannedCode(unique[0].text);
        } else if (unique.length > 1) {
          this.scannerPaused = true;
          this.scannerCandidates = unique;
        }
      } catch (e) {
        // Frame konnte nicht dekodiert werden; beim nächsten Frame erneut versuchen
      } finally {
        this.scannerDecoding = false;
      }
    },

    resumeBarcodeScanner() {
      this.scannerCandidates = [];
      this.scannerError = "";
      this.scannerPaused = false;
      this.scheduleScannerTick();
    },

    async scanBarcodeFromFile(event) {
      const input = event.target;
      const file = input?.files?.[0];
      if (!file) return;
      this.scannerError = "";
      this.scannerCandidates = [];
      this.scannerPhotoLoading = true;
      this.configureZxingWasm();

      try {
        let results = [];
        try {
          const bitmap = await createImageBitmap(file);
          const maxDim = 2200;
          const scale =
            Math.max(bitmap.width, bitmap.height) > maxDim
              ? maxDim / Math.max(bitmap.width, bitmap.height)
              : 1;
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(bitmap.width * scale));
          canvas.height = Math.max(1, Math.round(bitmap.height * scale));
          const ctx = canvas.getContext("2d", { willReadFrequently: true });
          ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
          bitmap.close?.();
          const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
          results = await ZXingWASM.readBarcodes(imgData, {
            tryHarder: true,
            tryRotate: true,
            tryInvert: true,
            tryDownscale: true,
            maxNumberOfSymbols: 6,
          });
        } catch (decodeErr) {
          results = await ZXingWASM.readBarcodes(file, {
            tryHarder: true,
            tryRotate: true,
            tryInvert: true,
            tryDownscale: true,
            maxNumberOfSymbols: 6,
          });
        }

        const unique = this._extractUniqueBarcodes(results);
        if (unique.length === 1) {
          this.applyScannedCode(unique[0].text);
        } else if (unique.length > 1) {
          this.scannerPaused = true;
          this.scannerCandidates = unique;
        } else {
          this.scannerError =
            "Kein Barcode auf dem Foto erkannt. Bitte näher/schärfer fotografieren oder Code unten eintragen.";
        }
      } catch (err) {
        this.scannerError = `Foto konnte nicht ausgewertet werden (${err?.message || "unbekannter Fehler"}).`;
      } finally {
        this.scannerPhotoLoading = false;
        if (input) input.value = "";
      }
    },

    applyScannedCode(code) {
      if (!code || !code.trim()) return;
      const { rowIndex, field } = this.scannerTarget;
      if (this.form.items[rowIndex]) {
        this.form.items[rowIndex][field] = code.trim();
      }
      this.closeBarcodeScanner();
      this.showToast("Barcode übernommen", `${code.trim()} wurde eingetragen.`, "info");
    },

    stopBarcodeScanner() {
      if (this.scannerTimerId) {
        clearTimeout(this.scannerTimerId);
        this.scannerTimerId = null;
      }
      if (this.scannerStream) {
        this.scannerStream.getTracks().forEach((track) => {
          try {
            track.stop();
          } catch (e) {
            // ignore
          }
        });
      }
      const videoEl = document.getElementById("scanner-video");
      if (videoEl) {
        videoEl.srcObject = null;
      }
      this.scannerStream = null;
      this.scannerTrack = null;
      this.scannerActive = false;
      this.scannerStarting = false;
      this.scannerDecoding = false;
      this.scannerTorchOn = false;
    },

    closeBarcodeScanner() {
      this.stopBarcodeScanner();
      const dlg = document.getElementById("scanner-dialog");
      if (dlg && dlg.open) {
        dlg.close();
      }
    },

    // =========================================================================
    // Stufe 2: Übergabe & Digitale Unterschrift vor Ort
    // =========================================================================

    openHandoverView(note) {
      this.currentHandoverNote = note;
      this.completedResultNote = null;
      this.handoverError = "";

      const activeStaff = this.staffList.filter((s) => s.active);
      let defaultStaff = activeStaff.length > 0 ? activeStaff[0].name : "__custom__";
      let customStaffName = "";

      // Falls der aktuell angemeldete Benutzer in der Mitarbeiterliste steht, automatisch vorauswählen!
      if (this.currentUser && this.currentUser.full_name) {
        const match = activeStaff.find(
          (s) => s.name.toLowerCase() === this.currentUser.full_name.toLowerCase()
        );
        if (match) {
          defaultStaff = match.name;
        } else {
          defaultStaff = "__custom__";
          customStaffName = this.currentUser.full_name;
        }
      }

      this.handoverForm = {
        delivered_by_select: defaultStaff,
        delivered_by_custom: customStaffName,
        received_by: note.ordered_by || "",
        handover_notes: "",
      };

      this.activeTab = "handover";
      window.scrollTo({ top: 0, behavior: "smooth" });

      this.$nextTick(() => {
        this.initSignaturePad();
      });
    },

    resizeSignatureCanvas(preserveStrokes = false) {
      const canvas = document.getElementById("signature-canvas");
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;

      const existingData =
        preserveStrokes && this.signaturePad && !this.signaturePad.isEmpty()
          ? this.signaturePad.toData()
          : null;

      const ratio = Math.max(window.devicePixelRatio || 1, 1);
      canvas.width = Math.round(rect.width * ratio);
      canvas.height = Math.round(rect.height * ratio);
      const ctx = canvas.getContext("2d");
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, rect.width, rect.height);

      if (this.signaturePad) {
        this.signaturePad.clear();
        if (existingData) {
          this.signaturePad.fromData(existingData);
        }
      }
    },

    initSignaturePad() {
      const canvas = document.getElementById("signature-canvas");
      if (!canvas || typeof SignaturePad === "undefined") return;

      if (this.signaturePad) {
        this.signaturePad.off();
        this.signaturePad = null;
      }

      if (!this.signatureResizeBound) {
        this.signatureResizeBound = true;
        const onViewportChange = () => {
          if (this.activeTab === "handover" && this.signaturePad) {
            requestAnimationFrame(() => this.resizeSignatureCanvas(true));
          }
        };
        window.addEventListener("resize", onViewportChange);
        window.addEventListener("orientationchange", onViewportChange);
      }

      requestAnimationFrame(() => {
        this.resizeSignatureCanvas(false);
        this.signaturePad = new SignaturePad(canvas, {
          backgroundColor: "rgb(255, 255, 255)",
          penColor: "rgb(15, 23, 42)",
          minWidth: 1.2,
          maxWidth: 3.0,
        });
      });
    },

    clearSignature() {
      if (this.signaturePad) {
        this.signaturePad.clear();
      }
    },

    async submitHandover() {
      this.handoverError = "";
      if (!this.currentHandoverNote) return;

      const deliveredBy =
        this.handoverForm.delivered_by_select === "__custom__"
          ? this.handoverForm.delivered_by_custom.trim()
          : this.handoverForm.delivered_by_select.trim();

      if (!deliveredBy) {
        this.handoverError = "Bitte wählen oder geben Sie an, wer die Geräte übergibt (IT-Mitarbeiter / Azubi).";
        return;
      }

      if (!this.handoverForm.received_by || !this.handoverForm.received_by.trim()) {
        this.handoverError = "Bitte geben Sie den Namen der annehmenden Person vor Ort ein (Pflichtfeld).";
        const recInput = document.getElementById("handover-received-by");
        if (recInput) recInput.focus();
        return;
      }

      if (!this.signaturePad || this.signaturePad.isEmpty()) {
        this.handoverError = "Bitte lassen Sie den Empfang im Unterschriftsfeld digital quittieren (Pflichtfeld).";
        return;
      }

      const signatureDataUrl = this.signaturePad.toDataURL("image/png");

      this.isSubmitting = true;
      try {
        const completed = await this.apiFetch(
          `/api/delivery-notes/${this.currentHandoverNote.id}/complete`,
          {
            method: "POST",
            body: JSON.stringify({
              delivered_by: deliveredBy,
              received_by: this.handoverForm.received_by.trim(),
              handover_notes: this.handoverForm.handover_notes,
              signature_data: signatureDataUrl,
            }),
          }
        );

        this.completedResultNote = completed;
        this.currentHandoverNote = completed;

        await Promise.all([
          this.loadStats(),
          this.loadOpenNotes(),
          this.loadDraftAndReadyNotes(),
          this.loadArchivedNotes(),
        ]);

        if (
          completed.email_school_status === "FEHLER" ||
          completed.email_osticket_status === "FEHLER"
        ) {
          this.showToast(
            "Lieferschein abgeschlossen (E-Mail-Warnung)",
            "PDF wurde archiviert, aber beim SMTP-Versand trat ein Fehler auf.",
            "error"
          );
        } else {
          this.showToast(
            "Übergabe abgeschlossen!",
            `PDF für ${completed.delivery_number} wurde generiert und versendet.`,
            "success"
          );
        }
      } catch (err) {
        this.handoverError = err.message;
      } finally {
        this.isSubmitting = false;
      }
    },

    // =========================================================================
    // Archiv & E-Mail-Neuversand
    // =========================================================================

    openArchiveDetails(note) {
      this.selectedArchiveNote = note;
      const dlg = document.getElementById("detail-dialog");
      if (dlg && !dlg.open) {
        dlg.showModal();
      }
    },

    closeArchiveDetails() {
      const dlg = document.getElementById("detail-dialog");
      if (dlg && dlg.open) {
        dlg.close();
      }
    },

    async resendEmails(note) {
      this.resendingEmailId = note.id;
      try {
        const updated = await this.apiFetch(`/api/delivery-notes/${note.id}/resend-email`, {
          method: "POST",
        });
        if (this.selectedArchiveNote && this.selectedArchiveNote.id === note.id) {
          this.selectedArchiveNote = updated;
        }
        if (this.completedResultNote && this.completedResultNote.id === note.id) {
          this.completedResultNote = updated;
        }
        await Promise.all([this.loadArchivedNotes(), this.loadStats()]);

        if (
          updated.email_school_status === "FEHLER" ||
          updated.email_osticket_status === "FEHLER"
        ) {
          this.showToast(
            "Versand erneut fehlgeschlagen",
            updated.email_school_error || updated.email_osticket_error || "SMTP-Fehler",
            "error"
          );
        } else {
          this.showToast(
            "E-Mails versendet",
            `Lieferschein ${updated.delivery_number} wurde erfolgreich versendet.`,
            "success"
          );
        }
      } catch (err) {
        this.showToast("Fehler beim E-Mail-Versand", err.message, "error");
      } finally {
        this.resendingEmailId = null;
      }
    },

    // =========================================================================
    // Verwaltung (Schulen & IT-Mitarbeiter)
    // =========================================================================

    resetSchoolForm() {
      this.schoolForm = {
        id: null,
        name: "",
        short_code: "",
        email: "",
        cc_email: "",
        address: "",
        active: true,
      };
    },

    editSchool(school) {
      this.schoolForm = {
        id: school.id,
        name: school.name,
        short_code: school.short_code || "",
        email: school.email,
        cc_email: school.cc_email || "",
        address: school.address || "",
        active: school.active,
      };
    },

    async saveSchool() {
      try {
        const payload = {
          name: this.schoolForm.name.trim(),
          short_code: this.schoolForm.short_code ? this.schoolForm.short_code.trim() : null,
          email: this.schoolForm.email.trim(),
          cc_email: this.schoolForm.cc_email ? this.schoolForm.cc_email.trim() : null,
          address: this.schoolForm.address ? this.schoolForm.address.trim() : null,
          active: Boolean(this.schoolForm.active),
        };
        if (this.schoolForm.id) {
          await this.apiFetch(`/api/schools/${this.schoolForm.id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          this.showToast("Schule aktualisiert", payload.name, "success");
        } else {
          await this.apiFetch("/api/schools", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.showToast("Schule angelegt", payload.name, "success");
        }
        this.resetSchoolForm();
        await this.loadSchools();
      } catch (err) {
        this.showToast("Fehler beim Speichern der Schule", err.message, "error");
      }
    },

    async deleteSchool(school) {
      if (!confirm(`Schule "${school.name}" wirklich löschen?`)) return;
      try {
        await this.apiFetch(`/api/schools/${school.id}`, { method: "DELETE" });
        this.showToast("Schule gelöscht", school.name, "info");
        await this.loadSchools();
      } catch (err) {
        this.showToast("Fehler", err.message, "error");
      }
    },

    resetStaffForm() {
      this.staffForm = {
        id: null,
        name: "",
        role: "",
        email: "",
        active: true,
      };
    },

    editStaff(member) {
      this.staffForm = {
        id: member.id,
        name: member.name,
        role: member.role || "",
        email: member.email || "",
        active: member.active,
      };
    },

    async saveStaff() {
      try {
        const payload = {
          name: this.staffForm.name.trim(),
          role: this.staffForm.role ? this.staffForm.role.trim() : null,
          email: this.staffForm.email ? this.staffForm.email.trim() : null,
          active: Boolean(this.staffForm.active),
        };
        if (this.staffForm.id) {
          await this.apiFetch(`/api/staff/${this.staffForm.id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          });
          this.showToast("Mitarbeiter aktualisiert", payload.name, "success");
        } else {
          await this.apiFetch("/api/staff", {
            method: "POST",
            body: JSON.stringify(payload),
          });
          this.showToast("Mitarbeiter angelegt", payload.name, "success");
        }
        this.resetStaffForm();
        await this.loadStaff();
      } catch (err) {
        this.showToast("Fehler beim Speichern", err.message, "error");
      }
    },

    async deleteStaff(member) {
      if (!confirm(`Mitarbeiter "${member.name}" wirklich löschen?`)) return;
      try {
        await this.apiFetch(`/api/staff/${member.id}`, { method: "DELETE" });
        this.showToast("Mitarbeiter gelöscht", member.name, "info");
        await this.loadStaff();
      } catch (err) {
        this.showToast("Fehler", err.message, "error");
      }
    },

    // =========================================================================
    // Formatierungs-Helfer
    // =========================================================================

    formatDate(isoStr) {
      if (!isoStr) return "–";
      try {
        const d = new Date(isoStr);
        return d.toLocaleDateString("de-DE", {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
        });
      } catch {
        return isoStr;
      }
    },

    formatDateTime(isoStr) {
      if (!isoStr) return "–";
      try {
        const d = new Date(isoStr);
        return d.toLocaleString("de-DE", {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
      } catch {
        return isoStr;
      }
    },

    emailBadgeClass(status) {
      switch (status) {
        case "VERSENDET":
          return "bg-emerald-100 text-emerald-800 border-emerald-300";
        case "SIMULIERT":
          return "bg-sky-100 text-sky-800 border-sky-300";
        case "FEHLER":
          return "bg-red-100 text-red-800 border-red-300";
        case "KEIN_TICKET":
          return "bg-slate-100 text-slate-600 border-slate-200";
        case "NICHT_KONFIGURIERT":
          return "bg-amber-100 text-amber-800 border-amber-300";
        default:
          return "bg-slate-100 text-slate-700 border-slate-300";
      }
    },

    emailStatusLabel(status) {
      switch (status) {
        case "VERSENDET":
          return "Versendet";
        case "SIMULIERT":
          return "Simuliert (Testmodus)";
        case "FEHLER":
          return "Versandfehler";
        case "KEIN_TICKET":
          return "Kein Ticket";
        case "NICHT_KONFIGURIERT":
          return "Nicht konfiguriert";
        case "AUSSTEHEND":
          return "Ausstehend";
        default:
          return status || "–";
      }
    },
  };
}
