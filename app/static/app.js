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
    // Navigation: 'deliveries' | 'prepare' | 'handover' | 'archive' | 'admin'
    activeTab: "deliveries",
    isLoading: false,
    isSubmitting: false,

    // App- & Auth-Status
    authEnabled: false,
    authenticated: true,
    authToken: localStorage.getItem("it_ls_token") || "",
    loginPin: "",
    loginError: "",
    appTitle: "Digitaler IT-Lieferschein",
    departmentName: "Stadtverwaltung – Schul-IT",
    smtpEnabled: false,
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

    // Lieferschein-Listen
    openNotes: [], // Status BEREIT
    draftAndReadyNotes: [], // Status ENTWURF + BEREIT (für Vorbereitungs-Übersicht)
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
      supplier: "",
      invoice_number: "",
      notes: "",
      status: "BEREIT",
      items: [
        { device_type: "", inventory_number: "", serial_number: "", quantity: 1 },
      ],
    },

    // Stufe 2: Übergabe & Unterschrift vor Ort
    currentHandoverNote: null,
    handoverForm: {
      delivered_by_select: "",
      delivered_by_custom: "",
      received_by: "",
      handover_notes: "",
      recipient_email: "",
      cc_email: "",
    },
    handoverError: "",
    signaturePad: null,
    completedResultNote: null,

    // Archiv-Detailansicht
    selectedArchiveNote: null,
    resendingEmailId: null,

    // Barcode-Scanner (html5-qrcode)
    html5QrCode: null,
    scannerActive: false,
    scannerTarget: { rowIndex: 0, field: "inventory_number" },
    scannerError: "",
    scannerManualCode: "",

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
      await this.checkAuthStatus();
      if (this.authenticated) {
        await this.loadInitialData();
      }
    },

    showToast(title, message = "", type = "success") {
      this.toast = { visible: true, title, message, type };
      setTimeout(() => {
        this.toast.visible = false;
      }, 4800);
    },

    async apiFetch(url, options = {}) {
      const headers = Object.assign(
        { "Content-Type": "application/json" },
        options.headers || {}
      );
      if (this.authToken) {
        headers["X-Auth-Token"] = this.authToken;
      }
      const response = await fetch(url, { ...options, headers });
      if (response.status === 401) {
        this.authenticated = false;
        const loginDlg = document.getElementById("login-dialog");
        if (loginDlg && !loginDlg.open) {
          loginDlg.showModal();
        }
        throw new Error("Bitte melden Sie sich mit Ihrer PIN an.");
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
        const res = await fetch("/api/auth/status", {
          headers: this.authToken ? { "X-Auth-Token": this.authToken } : {},
        });
        const data = await res.json();
        this.authEnabled = data.auth_enabled;
        this.authenticated = data.authenticated;
        this.appTitle = data.app_title || this.appTitle;
        this.departmentName = data.department_name || this.departmentName;
        this.smtpEnabled = data.smtp_enabled;
        this.osticketConfigured = data.osticket_configured;
        this.osticketEmail = data.osticket_email || "";

        if (this.authEnabled && !this.authenticated) {
          const loginDlg = document.getElementById("login-dialog");
          if (loginDlg && !loginDlg.open) {
            loginDlg.showModal();
          }
        }
      } catch (err) {
        console.error("Auth-Status konnte nicht geprüft werden:", err);
      }
    },

    async submitLogin() {
      this.loginError = "";
      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pin_or_password: this.loginPin }),
        });
        const data = await res.json();
        if (!res.ok) {
          this.loginError = data.detail || "Anmeldung fehlgeschlagen.";
          return;
        }
        this.authToken = data.token;
        localStorage.setItem("it_ls_token", data.token);
        this.authenticated = true;
        this.loginPin = "";
        const loginDlg = document.getElementById("login-dialog");
        if (loginDlg && loginDlg.open) {
          loginDlg.close();
        }
        await this.loadInitialData();
      } catch (err) {
        this.loginError = err.message || "Verbindungsfehler.";
      }
    },

    async logout() {
      await fetch("/api/auth/logout", { method: "POST" });
      localStorage.removeItem("it_ls_token");
      this.authToken = "";
      await this.checkAuthStatus();
    },

    async loadInitialData() {
      this.isLoading = true;
      try {
        await Promise.all([
          this.loadStats(),
          this.loadSchools(),
          this.loadStaff(),
          this.loadOpenNotes(),
          this.loadDraftAndReadyNotes(),
          this.loadArchivedNotes(),
        ]);
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
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
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
        supplier: "",
        invoice_number: "",
        notes: "",
        status: "BEREIT",
        items: [
          { device_type: "", inventory_number: "", serial_number: "", quantity: 1 },
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
      // Entferne '#', Leerzeichen und nicht-numerische Zeichen
      this.form.osticket_number = this.form.osticket_number.replace(/[^\d]/g, "");
    },

    addItemRow(focusIndex = null) {
      // Wenn die vorherige Zeile eine Gerätebezeichnung hat, übernehmen wir diese als Komfort-Vorschlag?
      // Nein, leer lassen, aber Button "Typ von oben übernehmen" anbieten!
      this.form.items.push({
        device_type: "",
        inventory_number: "",
        serial_number: "",
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
        this.form.items[index].device_type = this.form.items[index - 1].device_type;
        this.$nextTick(() => {
          const invInput = document.getElementById(`item-inv-${index}`);
          if (invInput) invInput.focus();
        });
      }
    },

    removeItemRow(index) {
      if (this.form.items.length <= 1) {
        this.form.items[0] = { device_type: "", inventory_number: "", serial_number: "", quantity: 1 };
        return;
      }
      this.form.items.splice(index, 1);
    },

    /**
     * Schnelle Tastatur- und USB-Barcodescanner-Navigation:
     * Enter im Feld "Gerätebezeichnung" -> springt zu "Inventarnummer"
     * Enter im Feld "Inventarnummer" -> springt zu "Seriennummer"
     * Enter im Feld "Seriennummer" -> legt neue Zeile an (oder springt in nächste Zeile)
     * Prüft KeyboardEvent.isComposing gemäß modern-web-guidance (Guide: forms).
     */
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
          const currentType = this.form.items[index].device_type;
          this.form.items.push({
            device_type: currentType, // Praktisch für Serien-Scans gleicher Geräte!
            inventory_number: "",
            serial_number: "",
            quantity: 1,
          });
          this.$nextTick(() => {
            const nextIndex = index + 1;
            const targetId = currentType ? `item-inv-${nextIndex}` : `item-type-${nextIndex}`;
            const nextEl = document.getElementById(targetId);
            if (nextEl) nextEl.focus();
          });
        } else {
          const nextEl = document.getElementById(`item-inv-${index + 1}`);
          if (nextEl) nextEl.focus();
        }
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
        supplier: note.supplier || "",
        invoice_number: note.invoice_number || "",
        notes: note.notes || "",
        status: note.status === "ENTWURF" ? "ENTWURF" : "BEREIT",
        items:
          note.items && note.items.length > 0
            ? note.items.map((i) => ({
                device_type: i.device_type,
                inventory_number: i.inventory_number,
                serial_number: i.serial_number || "",
                quantity: i.quantity || 1,
              }))
            : [{ device_type: "", inventory_number: "", serial_number: "", quantity: 1 }],
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
          supplier: this.form.supplier,
          invoice_number: this.form.invoice_number,
          notes: this.form.notes,
          status: targetStatus,
          items: validItems.map((i) => ({
            device_type: i.device_type.trim(),
            inventory_number: i.inventory_number.trim(),
            serial_number: i.serial_number ? i.serial_number.trim() : null,
            quantity: Number(i.quantity) || 1,
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
    // Kamera-Barcode-Scanner (html5-qrcode) im nativen <dialog>
    // =========================================================================

    async openBarcodeScanner(rowIndex, field) {
      this.scannerTarget = { rowIndex, field };
      this.scannerError = "";
      this.scannerManualCode = "";

      const dlg = document.getElementById("scanner-dialog");
      if (dlg && !dlg.open) {
        dlg.showModal();
      }

      await this.$nextTick();
      if (typeof Html5Qrcode === "undefined") {
        this.scannerError = "Barcode-Scanner-Bibliothek nicht geladen. Bitte Code unten manuell eingeben.";
        return;
      }

      try {
        if (this.html5QrCode && this.scannerActive) {
          await this.stopBarcodeScanner();
        }
        this.html5QrCode = new Html5Qrcode("qr-reader");
        this.scannerActive = true;
        await this.html5QrCode.start(
          { facingMode: "environment" },
          { fps: 10, qrbox: { width: 250, height: 120 } },
          (decodedText) => {
            this.applyScannedCode(decodedText);
          },
          () => {}
        );
      } catch (err) {
        this.scannerActive = false;
        this.scannerError =
          "Kamerazugriff nicht möglich (HTTPS oder Berechtigung erforderlich). Sie können den Barcode unten direkt per Handscanner oder Tastatur eintragen.";
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

    async stopBarcodeScanner() {
      if (this.html5QrCode && this.scannerActive) {
        try {
          await this.html5QrCode.stop();
          await this.html5QrCode.clear();
        } catch (e) {
          // ignore
        }
      }
      this.scannerActive = false;
    },

    async closeBarcodeScanner() {
      await this.stopBarcodeScanner();
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
      const defaultStaff = activeStaff.length > 0 ? activeStaff[0].name : "__custom__";

      this.handoverForm = {
        delivered_by_select: defaultStaff,
        delivered_by_custom: "",
        received_by: note.ordered_by || "",
        handover_notes: "",
        recipient_email: note.recipient_email || "",
        cc_email: note.cc_email || "",
      };

      this.activeTab = "handover";
      window.scrollTo({ top: 0, behavior: "smooth" });

      this.$nextTick(() => {
        this.initSignaturePad();
      });
    },

    initSignaturePad() {
      const canvas = document.getElementById("signature-canvas");
      if (!canvas || typeof SignaturePad === "undefined") return;

      const resizeCanvas = () => {
        const ratio = Math.max(window.devicePixelRatio || 1, 1);
        const rect = canvas.getBoundingClientRect();
        const width = rect.width || 600;
        const height = rect.height || 220;
        canvas.width = width * ratio;
        canvas.height = height * ratio;
        const ctx = canvas.getContext("2d");
        ctx.scale(ratio, ratio);
        // Weißer Hintergrund für sauberen PNG-Export im PDF
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, width, height);
      };

      resizeCanvas();
      this.signaturePad = new SignaturePad(canvas, {
        backgroundColor: "rgb(255, 255, 255)",
        penColor: "rgb(15, 23, 42)",
        minWidth: 1.2,
        maxWidth: 3.0,
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
              recipient_email: this.handoverForm.recipient_email,
              cc_email: this.handoverForm.cc_email,
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
