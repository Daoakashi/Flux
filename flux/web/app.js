/* Interface web de Flux : servie par le serveur FluxLite du PC (https://<adresse du PC>:<port>/).
 *
 * Mêmes comptes, mêmes caméras et mêmes droits que l'application FluxLite.
 *
 * Ce PC (« ici ») : la session est gardée dans un cookie HttpOnly posé par le serveur, que ce code ne voit jamais.
 * Chaque requête qui modifie quelque chose porte l'en-tête « X-Flux: web », qu'un autre site ne peut pas ajouter.
 *
 * Autres PC Flux (un directeur qui suit plusieurs établissements) : le navigateur les appelle lui-même, avec une
 * session propre à chacun (jeton « Bearer », gardé dans ce navigateur et lié au compte connecté ici). Chaque
 * serveur garde ses propres comptes et ses propres droits. Aucune bibliothèque externe, rien ne part sur Internet.
 */
"use strict";
(() => {
  const VERSION_WEB = "2.0";
  const API = "api/v1/";
  const NOMS_NIVEAUX = { alerte: "Alerte", action: "Action", video: "Vidéo" };
  const FEEDBACK_MAIL = "dms.security.list@gmail.com";
  const FEEDBACK_GITHUB = "https://github.com/Daoakashi/Flux/issues/new";

  const etat = {
    info: null, compte: null, vue: "cameras", camera: null,
    serveurs: [],          // [{id, local, url, nom, jeton, affiche, cameras, compte, pilotage, erreur, en_ligne}]
    nonLues: 0, minuteurs: [], ecoute: 0, journal: [], filtreCamera: "", finJournal: false, pilotageSrv: "ici",
  };

  // --- petits outils -------------------------------------------------------------------------------------------
  const $ = (sel, racine = document) => racine.querySelector(sel);

  function el(tag, attrs, ...enfants) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "style") n.style.cssText = v;  // par le CSSOM : permis par la politique de sécurité (CSP)
      else if (k === "texte") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k in n && typeof v !== "string") n[k] = v;
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const e of enfants.flat()) if (e !== null && e !== undefined && e !== false) n.append(e);
    return n;
  }

  const ICONES = {
    camera: '<path d="M3 8a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="m16 10 5-3v10l-5-3"/>',
    alerte: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    pilotage: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    compte: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    retour: '<path d="m15 18-6-6 6-6"/>',
    plein: '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    sortie: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    hors: '<path d="m2 2 20 20M10.4 6H14a2 2 0 0 1 2 2v3.6M16 16a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h1"/><path d="m16 10 5-3v10"/>',
    image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    cloche: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/><path d="M2 8c0-2.2.7-4.3 2-6M22 8a10 10 0 0 0-2-6"/>',
    video: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5" fill="currentColor"/>',
    cadenas: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    serveur: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    message: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5A8 8 0 1 1 21 12z"/><path d="M8.5 11h7M8.5 14h4"/>',
    lien: '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1.2 1.2"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2"/>',
  };
  function ic(nom) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "ic");
    s.setAttribute("aria-hidden", "true");
    s.innerHTML = ICONES[nom] || "";  // chaînes fixes de ce fichier, jamais de données reçues
    return s;
  }

  function inter(actif, surChange, { desactive = false, libelle = "" } = {}) {
    const b = el("button", { class: "inter", type: "button", role: "switch", "aria-checked": String(!!actif),
      "aria-label": libelle, disabled: desactive });
    b.addEventListener("click", async () => {
      const nouveau = b.getAttribute("aria-checked") !== "true";
      b.disabled = true;
      b.setAttribute("aria-checked", String(nouveau));
      try { await surChange(nouveau); } catch (e) { b.setAttribute("aria-checked", String(!nouveau)); toast(e.message, "", "erreur"); }
      finally { b.disabled = desactive; }
    });
    return b;
  }

  const fmtDate = new Intl.DateTimeFormat("fr-BE", { dateStyle: "medium", timeStyle: "short" });
  const fmtHeure = new Intl.DateTimeFormat("fr-BE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const fmtJour = new Intl.DateTimeFormat("fr-BE", { weekday: "short", day: "numeric", month: "short" });
  function date(t) { return t ? fmtDate.format(new Date(t * 1000)) : "—"; }
  function quand(t) {
    const d = new Date(t * 1000), maintenant = new Date();
    const s = Math.round((maintenant - d) / 1000);
    if (s < 60) return "à l'instant";
    if (s < 3600) return `il y a ${Math.floor(s / 60)} min`;
    if (d.toDateString() === maintenant.toDateString()) return fmtHeure.format(d).slice(0, 5);
    return `${fmtJour.format(d)} ${fmtHeure.format(d).slice(0, 5)}`;
  }

  function appareil() {
    const ua = navigator.userAgent;
    const nav = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera" : /Firefox\//.test(ua) ? "Firefox"
      : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Navigateur";
    const sys = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Windows/.test(ua) ? "Windows"
      : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
    return `Navigateur ${nav}${sys ? " · " + sys : ""}`;
  }

  const stock = {  // stockage du navigateur : peut être indisponible (navigation privée) sans rien casser
    lire(cle, defaut) { try { const v = localStorage.getItem(cle); return v === null ? defaut : JSON.parse(v); } catch { return defaut; } },
    ecrire(cle, v) { try { localStorage.setItem(cle, JSON.stringify(v)); } catch { /* ignoré */ } },
  };

  // --- échanges avec les PC Flux ---------------------------------------------------------------------------------
  class ErreurApi extends Error {
    constructor(message, code, donnees) { super(message); this.code = code; this.donnees = donnees || {}; }
  }

  const ICI = { id: "ici", local: true, url: "", nom: "", affiche: true, cameras: [], en_ligne: true };
  const srvIci = () => etat.serveurs.find((s) => s.local) || ICI;
  const srvPar = (id) => etat.serveurs.find((s) => s.id === id);
  const affiches = () => etat.serveurs.filter((s) => s.affiche && (s.local || s.jeton));
  const plusieurs = () => affiches().length > 1;

  function base(srv) { return srv && !srv.local ? `${srv.url}/${API}` : API; }

  function entetes(srv, json) {
    const e = srv && !srv.local ? { Authorization: `Bearer ${srv.jeton}` } : { "X-Flux": "web" };
    if (json) e["Content-Type"] = "application/json";
    return e;
  }

  async function api(chemin, { methode = "GET", corps, srv = null, sansJeton = false } = {}) {
    const distant = srv && !srv.local;
    const h = distant && sansJeton ? {} : entetes(srv, corps !== undefined);
    if (distant && sansJeton && corps !== undefined) h["Content-Type"] = "application/json";
    let r;
    try {
      r = await fetch(base(srv) + chemin, { method: methode, headers: h, cache: "no-store",
        credentials: distant ? "omit" : "same-origin", body: corps !== undefined ? JSON.stringify(corps) : undefined });
    } catch {
      throw new ErreurApi(distant
        ? `« ${srv.nom || srv.url} » ne répond pas. S'il est allumé, ouvrez une fois son adresse dans un onglet pour accepter son certificat.`
        : "Le PC Flux ne répond pas. Vérifiez qu'il est allumé et sur le même réseau.", 0);
    }
    let d = null;
    try { d = await r.json(); } catch { /* réponse vide */ }
    if (r.status === 401 && chemin !== "connexion") {
      if (!srv || srv.local) { if (etat.compte) sessionPerdue(d && d.erreur); }
      else if (srv.jeton) sessionDistantePerdue(srv);
    }
    if (!r.ok) throw new ErreurApi(d && d.erreur || `Erreur ${r.status}`, r.status, d);
    return d;
  }

  // Images d'un autre PC Flux : le navigateur ne peut pas ajouter le jeton à une balise <img>, on passe par fetch
  async function urlImage(srv, chemin) {
    if (srv.local) return `${API}${chemin}`;
    const r = await fetch(base(srv) + chemin, { headers: entetes(srv), credentials: "omit", cache: "no-store" });
    if (!r.ok) throw new Error(String(r.status));
    return URL.createObjectURL(await r.blob());
  }

  // Vidéo en direct (MJPEG) d'un autre PC Flux : lecture du flux et découpage des images JPEG
  function lireDirectDistant(srv, chemin, img, surErreur) {
    const ctrl = new AbortController();
    const SEP = new TextEncoder().encode("\r\n\r\n");
    const chercher = (t, motif, depuis = 0) => {
      outer: for (let i = depuis; i <= t.length - motif.length; i++) {
        for (let j = 0; j < motif.length; j++) if (t[i + j] !== motif[j]) continue outer;
        return i;
      }
      return -1;
    };
    (async () => {
      let precedente = null;
      try {
        const r = await fetch(base(srv) + chemin, { headers: entetes(srv), credentials: "omit", signal: ctrl.signal });
        if (!r.ok || !r.body) throw new Error(String(r.status));
        const lecteur = r.body.getReader();
        let tampon = new Uint8Array(0);
        for (;;) {
          const { value, done } = await lecteur.read();
          if (done) break;
          const t = new Uint8Array(tampon.length + value.length);
          t.set(tampon); t.set(value, tampon.length); tampon = t;
          for (;;) {
            const fin = chercher(tampon, SEP);
            if (fin < 0) break;
            const entete = new TextDecoder().decode(tampon.subarray(0, fin));
            const m = /Content-Length:\s*(\d+)/i.exec(entete);
            if (!m) { tampon = tampon.subarray(fin + 4); continue; }
            const n = Number(m[1]);
            if (tampon.length < fin + 4 + n) break;
            const url = URL.createObjectURL(new Blob([tampon.slice(fin + 4, fin + 4 + n)], { type: "image/jpeg" }));
            img.src = url;
            if (precedente) URL.revokeObjectURL(precedente);
            precedente = url;
            tampon = tampon.slice(fin + 4 + n);
          }
        }
      } catch (e) {
        if (e.name !== "AbortError") surErreur();
      }
    })();
    return () => ctrl.abort();
  }

  // --- notifications à l'écran ----------------------------------------------------------------------------------
  function toast(titre, texte = "", genre = "", surClic = null) {
    const t = el("div", { class: `toast ${genre}`, role: genre === "erreur" ? "alert" : "status" },
      el("div", {}, el("b", { texte: titre }), texte ? el("span", { texte }) : null));
    const fermer = () => t.remove();
    t.addEventListener("click", () => { fermer(); if (surClic) surClic(); });
    const zone = $("#toasts");
    zone.append(t);
    while (zone.children.length > 4) zone.firstChild.remove();
    setTimeout(fermer, genre === "alerte" ? 9000 : 5000);
  }

  function fenetre(contenu, surFermer = null) {
    const voile = el("div", { class: "voile" });
    const fermer = () => { voile.remove(); document.removeEventListener("keydown", touche); if (surFermer) surFermer(); };
    const touche = (e) => { if (e.key === "Escape") fermer(); };
    voile.addEventListener("click", (e) => { if (e.target === voile) fermer(); });
    voile.append(contenu);
    document.body.append(voile);
    document.addEventListener("keydown", touche);
    return fermer;
  }

  function confirmer(titre, texte, libelle, { danger = false, champMdp = false } = {}) {
    return new Promise((resolve) => {
      let valeur = null;
      const mdp = champMdp ? el("input", { type: "password", autocomplete: "current-password", required: true }) : null;
      const ok = el("button", { class: `btn ${danger ? "danger" : "principal"}`, type: "submit", texte: libelle });
      const form = el("form", { class: "fenetre", role: "dialog", "aria-modal": "true",
        onsubmit: (e) => { e.preventDefault(); valeur = champMdp ? mdp.value : true; fermer(); } },
        el("h3", { texte: titre }), el("p", { texte }),
        mdp ? el("div", { class: "champ" }, el("label", { texte: "Mot de passe" }), mdp) : null,
        el("div", { class: "boutons" },
          el("button", { class: "btn fantome", type: "button", texte: "Annuler", onclick: () => fermer() }), ok));
      const fermer = fenetre(form, () => resolve(valeur));
      (mdp || ok).focus();
    });
  }

  // --- Feedback (dans chaque programme Flux) ------------------------------------------------------------------------
  function feedback() {
    const contexte = `Programme : interface web de Flux ${VERSION_WEB}\nFlux (PC) : ${etat.info?.version_flux || "?"}\n`
      + `Navigateur : ${appareil()}\nÉcran : ${innerWidth}×${innerHeight}\n`;
    const sujet = el("select", { "aria-label": "Type de retour" },
      ["Idée ou suggestion", "Problème (bug)", "Question", "Autre"].map((t) => el("option", { value: t, texte: t })));
    const texte = el("textarea", { rows: 6, placeholder: "Décrivez votre idée ou le problème rencontré…", maxlength: 4000,
      style: "width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--trait);background:var(--panneau);font:inherit;resize:vertical" });
    const corps = () => `${texte.value.trim()}\n\n---\n${contexte}`;
    const fermer = fenetre(el("div", { class: "fenetre", role: "dialog", "aria-modal": "true", style: "max-width:520px" },
      el("h3", { texte: "Feedback" }),
      el("p", { texte: "Une idée, un problème, une question ? Votre message aide à améliorer Flux. N'y mettez ni mot de passe ni image des caméras." }),
      el("div", { class: "champ" }, el("label", { texte: "Sujet" }), sujet),
      el("div", { class: "champ" }, el("label", { texte: "Message" }), texte),
      el("div", { class: "boutons" },
        el("button", { class: "btn fantome", type: "button", texte: "Annuler", onclick: () => fermer() }),
        el("a", { class: "btn", target: "_blank", rel: "noopener", onclick: (e) => {
          e.currentTarget.href = `${FEEDBACK_GITHUB}?title=${encodeURIComponent(`[${sujet.value}] `)}&body=${encodeURIComponent(corps())}`;
          setTimeout(fermer, 100);
        } }, ic("lien"), "Signaler sur GitHub"),
        el("a", { class: "btn principal", onclick: (e) => {
          e.currentTarget.href = `mailto:${FEEDBACK_MAIL}?subject=${encodeURIComponent(`Flux web · ${sujet.value}`)}&body=${encodeURIComponent(corps())}`;
          setTimeout(fermer, 100);
        } }, ic("message"), "Envoyer par mail"))));
    texte.focus();
  }

  // --- minuteurs de la vue courante -----------------------------------------------------------------------------
  const arrets = [];
  function repeter(fn, ms) {
    const id = setInterval(() => { if (!document.hidden) fn(); }, ms);
    etat.minuteurs.push(id);
  }
  function arreterMinuteurs() {
    etat.minuteurs.forEach(clearInterval);
    etat.minuteurs = [];
    arrets.splice(0).forEach((f) => f());
    // ferme les vidéos en direct : le PC limite le nombre de vidéos ouvertes par compte
    document.querySelectorAll("img[data-direct]").forEach((i) => { i.removeAttribute("src"); });
  }

  // ===============================================================================================================
  // Démarrage
  // ===============================================================================================================
  async function demarrer() {
    try {
      etat.info = await api("info");
    } catch (e) {
      return afficherErreurDemarrage(e.message);
    }
    document.title = etat.info.nom ? `${etat.info.nom} — Flux` : "Flux";
    try {
      etat.compte = await api("compte");
    } catch {
      etat.compte = null;
    }
    if (etat.compte) entrer(); else ecranConnexion();
  }

  function afficherErreurDemarrage(message) {
    monter(el("div", { class: "ecran-connexion" }, el("div", { class: "boite" }, marque("Flux", "Interface web"),
      el("div", { class: "msg erreur", texte: message }),
      el("button", { class: "btn principal large", texte: "Réessayer", onclick: () => location.reload() }))));
  }

  function monter(noeud) {
    arreterMinuteurs();
    $("#app").replaceChildren(noeud);
  }

  function marque(titre, sous) {
    return el("div", { class: "marque" }, el("img", { src: "icone.svg", alt: "" }),
      el("div", {}, el("h1", { texte: titre }), el("p", { texte: sous })));
  }

  // ===============================================================================================================
  // Connexion, inscription, conditions d'utilisation
  // ===============================================================================================================
  function ecranConnexion(message = "", genre = "erreur", mail = "") {
    etat.compte = null;
    const info = etat.info;
    const msg = el("div", { class: `msg ${genre}`, role: "alert", hidden: !message, texte: message });
    const champMail = el("input", { type: "email", id: "mail", autocomplete: "username", required: true, value: mail,
      inputmode: "email", autocapitalize: "none", spellcheck: false });
    const champMdp = el("input", { type: "password", id: "mdp", autocomplete: "current-password", required: true });
    const bouton = el("button", { class: "btn principal large", type: "submit", texte: "Se connecter" });

    async function envoyer(e) {
      e.preventDefault();
      bouton.disabled = true;
      bouton.replaceChildren(el("span", { class: "roue petite" }), " Connexion…");
      msg.hidden = true;
      try {
        const d = await api("connexion", { methode: "POST", corps: { mail: champMail.value.trim(),
          mot_de_passe: champMdp.value, web: true, appareil: appareil(), version_app: `Web ${VERSION_WEB}` } });
        etat.compte = d.compte;
        entrer();
      } catch (err) {
        msg.className = `msg ${err.donnees.statut === "attente" ? "info" : "erreur"}`;
        msg.textContent = err.message;
        msg.hidden = false;
        champMdp.value = "";
        champMdp.focus();
        bouton.disabled = false;
        bouton.textContent = "Se connecter";
      }
    }

    monter(el("div", { class: "ecran-connexion" },
      el("form", { class: "boite", onsubmit: envoyer },
        marque(info.nom || "Flux", "Interface web · connexion"),
        msg,
        el("div", { class: "champ" }, el("label", { for: "mail", texte: "Adresse mail" }), champMail),
        el("div", { class: "champ" }, el("label", { for: "mdp", texte: "Mot de passe" }), champMdp),
        bouton,
        info.inscription
          ? el("div", { class: "lien-bas" }, "Pas encore de compte ? ",
            el("button", { type: "button", texte: "Créer un compte", onclick: () => ecranInscription() }))
          : el("div", { class: "lien-bas", texte: "Les comptes sont créés par votre responsable." }),
        el("div", { class: "pied" }, ic("cadenas"), ` Connexion chiffrée avec ce PC · Flux ${info.version_flux || ""}`),
        el("div", { class: "lien-bas", style: "margin-top:6px" },
          el("button", { type: "button", texte: "Feedback", onclick: feedback })))));
    (mail ? champMdp : champMail).focus();
  }

  function texteCgu(i) {
    const resp = (i.responsable || "").trim() || "l'entreprise qui exploite ce serveur Flux";
    const contact = (i.contact || "").trim() ? ` à l'adresse ${i.contact.trim()}` : " auprès de ce responsable";
    const duree = i.conservation_journal || 7;
    return [
      ["1. Objet", "L'interface web de Flux, comme l'application FluxLite, permet aux personnes autorisées de consulter en direct les caméras d'un système de vidéosurveillance Flux et d'en recevoir les alertes. Elle ne fonctionne qu'avec un serveur Flux privé ; ce n'est pas un service public."],
      ["2. Accès et compte", "Votre compte est personnel. Il est validé par le responsable du serveur, qui décide des caméras auxquelles vous avez accès. Vous gardez votre mot de passe secret et signalez sans délai toute utilisation suspecte. Le responsable peut suspendre ou supprimer un compte à tout moment."],
      ["3. Bon usage des images", "Les images montrent des personnes : ce sont des données personnelles. Vous les consultez uniquement pour la mission de sécurité qui vous est confiée. Il est interdit de les enregistrer, de faire des captures d'écran, de les diffuser ou de les utiliser à d'autres fins. Toute infraction peut entraîner la suppression du compte et engager votre responsabilité."],
      ["4. Responsable du traitement", `Le responsable du traitement de vos données est ${resp}. Les données sont stockées sur son propre serveur Flux, et non chez l'éditeur du logiciel ni chez un hébergeur tiers.`],
      ["5. Données vous concernant", "Nom, prénom, adresse mail, société indiquée, empreinte chiffrée du mot de passe (jamais le mot de passe lui-même), date d'acceptation des présentes conditions, et des informations techniques de connexion : navigateur ou modèle de l'appareil, version, adresse IP, dates de connexion. Elles servent à sécuriser l'accès (base légale : exécution du contrat et intérêt légitime de sécurité) et sont conservées tant que le compte existe."],
      ["6. Alertes et journal", `Les alertes et leurs photos sont conservées ${duree} jour(s) sur le serveur puis effacées. Le navigateur garde seulement les sessions ouvertes, sans aucune donnée personnelle.`],
      ["7. Sécurité", "Les échanges sont chiffrés (TLS) avec le certificat propre à chaque PC Flux. Les sessions peuvent être fermées à tout moment depuis l'onglet Compte."],
      ["8. Vos droits (RGPD)", `Vous pouvez accéder à vos données, les rectifier, les exporter, demander leur effacement, vous opposer à leur traitement ou en demander la limitation. L'onglet Compte permet d'exporter vos données et de supprimer votre compte. Pour toute autre demande, adressez-vous au responsable${contact}. Vous pouvez aussi saisir l'autorité de protection des données (APD en Belgique, CNIL en France).`],
      ["9. Évolution", `Ces conditions peuvent évoluer ; la nouvelle version vous sera présentée et devra être acceptée pour continuer. Version ${i.cgu_version}.`],
    ];
  }
  function blocCgu(info = etat.info) {
    return el("div", { class: "cgu", tabindex: "0" }, texteCgu(info).map(([t, p]) => [el("h4", { texte: t }), el("p", { texte: p })]));
  }

  function ecranInscription() {
    const msg = el("div", { class: "msg erreur", role: "alert", hidden: true });
    const champ = (id, libelle, attrs = {}, aide = "") => el("div", { class: "champ" },
      el("label", { for: id, texte: libelle }), el("input", { id, ...attrs }), aide ? el("div", { class: "aide", texte: aide }) : null);
    const coche = el("input", { type: "checkbox", id: "cgu" });
    const bouton = el("button", { class: "btn principal large", type: "submit", texte: "Créer mon compte" });

    async function envoyer(e) {
      e.preventDefault();
      const f = e.target, v = (id) => $(`#${id}`, f).value;
      msg.hidden = true;
      const erreur = v("i_mdp") !== v("i_mdp2") ? "Les deux mots de passe ne sont pas identiques."
        : !coche.checked ? "Vous devez accepter les conditions d'utilisation." : "";
      if (erreur) { msg.textContent = erreur; msg.hidden = false; return; }
      bouton.disabled = true;
      try {
        const d = await api("inscription", { methode: "POST", corps: { prenom: v("i_prenom").trim(), nom: v("i_nom").trim(),
          mail: v("i_mail").trim(), societe: v("i_societe").trim(), mot_de_passe: v("i_mdp"),
          cgu_version: etat.info.cgu_version, appareil: appareil(), version_app: `Web ${VERSION_WEB}` } });
        ecranConnexion(d.message, "ok", v("i_mail").trim());
      } catch (err) {
        msg.textContent = err.message;
        msg.hidden = false;
        bouton.disabled = false;
        msg.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }

    monter(el("div", { class: "ecran-connexion" },
      el("form", { class: "boite large", onsubmit: envoyer },
        marque(etat.info.nom || "Flux", "Créer un compte"),
        msg,
        el("div", { class: "ligne-champs" },
          champ("i_prenom", "Prénom", { required: true, autocomplete: "given-name", maxlength: 60 }),
          champ("i_nom", "Nom", { required: true, autocomplete: "family-name", maxlength: 60 })),
        champ("i_mail", "Adresse mail", { type: "email", required: true, autocomplete: "email", autocapitalize: "none" }),
        champ("i_societe", "Société", { autocomplete: "organization", maxlength: 120 }, "Celle pour laquelle vous surveillez, ex. le nom du magasin."),
        el("div", { class: "ligne-champs" },
          champ("i_mdp", "Mot de passe", { type: "password", required: true, minlength: 10, autocomplete: "new-password" }),
          champ("i_mdp2", "Confirmer", { type: "password", required: true, minlength: 10, autocomplete: "new-password" })),
        el("div", { class: "aide", style: "margin:-8px 0 14px;font-size:12.5px;color:var(--texte3)",
          texte: "Au moins 10 caractères, avec au moins une lettre et un chiffre." }),
        blocCgu(),
        el("label", { class: "case" }, coche, "J'ai lu les conditions d'utilisation et l'information sur mes données personnelles."),
        bouton,
        el("div", { class: "lien-bas" }, "Déjà un compte ? ",
          el("button", { type: "button", texte: "Se connecter", onclick: () => ecranConnexion() })))));
    $("#i_prenom").focus();
  }

  function ecranNouvellesCgu() {
    const coche = el("input", { type: "checkbox" });
    const bouton = el("button", { class: "btn principal large", type: "submit", texte: "J'accepte les conditions d'utilisation", disabled: true });
    coche.addEventListener("change", () => { bouton.disabled = !coche.checked; });
    monter(el("div", { class: "ecran-connexion" },
      el("form", { class: "boite large", onsubmit: async (e) => {
        e.preventDefault();
        bouton.disabled = true;
        try {
          etat.compte = await api("compte", { methode: "PATCH", corps: { cgu_version: etat.info.cgu_version } });
          entrer();
        } catch (err) { toast(err.message, "", "erreur"); bouton.disabled = false; }
      } },
        marque("Conditions d'utilisation", "Elles ont changé : merci de les relire"),
        blocCgu(),
        el("label", { class: "case" }, coche, "J'ai lu les conditions d'utilisation et l'information sur mes données personnelles."),
        bouton,
        el("div", { class: "lien-bas" }, el("button", { type: "button", texte: "Se déconnecter", onclick: deconnecter })))));
  }

  async function deconnecter() {
    // ferme aussi les sessions des autres PC Flux ouvertes depuis ce navigateur
    for (const s of etat.serveurs.filter((x) => !x.local && x.jeton)) {
      try { await api("deconnexion", { methode: "POST", srv: s }); } catch { /* injoignable : la session expirera */ }
      s.jeton = null;
    }
    sauverServeurs();
    try { await api("deconnexion", { methode: "POST" }); } catch { /* déjà déconnecté */ }
    etat.ecoute++;
    etat.compte = null;
    etat.serveurs = [];
    ecranConnexion("Vous êtes déconnecté.", "info");
  }

  function sessionPerdue(message) {
    if (!etat.compte) return;
    etat.ecoute++;
    etat.compte = null;
    etat.serveurs = [];
    ecranConnexion(message || "Session expirée : reconnectez-vous.", "info");
  }

  function sessionDistantePerdue(srv) {
    srv.jeton = null;
    srv.erreur = "Session expirée : reconnectez-vous (Compte › Serveurs).";
    sauverServeurs();
    toast(`${srv.nom} : session expirée`, "Reconnectez ce serveur dans Compte › Serveurs.", "erreur", () => { location.hash = "#/compte"; });
  }

  // ===============================================================================================================
  // Plusieurs PC Flux
  // ===============================================================================================================
  const cleServeurs = () => `flux.serveurs.${etat.compte?.id || "?"}@${location.host}`;

  function chargerServeurs() {
    const ici = { ...ICI, nom: etat.compte.serveur || etat.info.nom || "Ce PC", affiche: stock.lire(`${cleServeurs()}.ici`, true) };
    const autres = stock.lire(cleServeurs(), []).filter((s) => s && typeof s.url === "string").map((s) => ({
      id: s.url, local: false, url: s.url, nom: s.nom || s.url, jeton: s.jeton || null, affiche: s.affiche !== false,
      cle: s.cle || "", cameras: [], en_ligne: true, erreur: s.jeton ? "" : "Pas de session : reconnectez ce serveur.",
    }));
    etat.serveurs = [ici, ...autres];
  }

  function sauverServeurs() {
    if (!etat.compte) return;
    stock.ecrire(cleServeurs(), etat.serveurs.filter((s) => !s.local)
      .map((s) => ({ url: s.url, nom: s.nom, jeton: s.jeton, affiche: s.affiche, cle: s.cle })));
    stock.ecrire(`${cleServeurs()}.ici`, srvIci().affiche);
  }

  function normaliserAdresse(texte) {
    let t = String(texte || "").trim().replace(/\/+$/, "");
    if (!t) return "";
    if (!/^https?:\/\//i.test(t)) t = `https://${t}`;
    try {
      const u = new URL(t);
      return `https://${u.hostname.includes(":") ? `[${u.hostname.replace(/^\[|\]$/g, "")}]` : u.hostname}:${u.port || 47810}`;
    } catch { return ""; }
  }

  // ===============================================================================================================
  // Application
  // ===============================================================================================================
  const VUES = {
    cameras: { titre: "Caméras", icone: "camera" },
    alertes: { titre: "Alertes", icone: "alerte" },
    pilotage: { titre: "Pilotage", icone: "pilotage" },
    compte: { titre: "Compte", icone: "compte" },
  };

  const droitPilotage = () => etat.serveurs.some((s) => (s.local ? etat.compte?.pilotage : s.compte?.pilotage) && (s.local || s.jeton));

  function entrer() {
    if (!etat.compte.cgu_a_jour) return ecranNouvellesCgu();
    chargerServeurs();
    ecouterAlertes();
    if (!location.hash) history.replaceState(null, "", "#/cameras");
    router();
    // profils des autres serveurs (droit de pilotage, nom) en arrière-plan
    for (const s of etat.serveurs.filter((x) => !x.local && x.jeton)) {
      api("compte", { srv: s }).then((c) => { s.compte = c; s.nom = c.serveur || s.nom; s.erreur = ""; sauverServeurs(); majNavigation(); })
        .catch((e) => { s.erreur = e.message; });
    }
  }

  function router() {
    if (!etat.compte) return;
    const morceaux = location.hash.split("/");
    const vue = morceaux[1] || "cameras";
    if (vue === "camera" && morceaux[3]) return afficher("cameras", { srv: decodeURIComponent(morceaux[2]), id: decodeURIComponent(morceaux[3]) });
    afficher(VUES[vue] && (vue !== "pilotage" || droitPilotage()) ? vue : "cameras");
  }
  window.addEventListener("hashchange", router);

  function navigation() {
    const lien = (cle) => {
      const v = VUES[cle];
      const a = el("a", { href: `#/${cle}`, "aria-current": etat.vue === cle ? "page" : null }, ic(v.icone), el("span", { texte: v.titre }));
      if (cle === "alertes" && etat.nonLues) a.append(el("span", { class: "pastille", texte: etat.nonLues > 99 ? "99+" : String(etat.nonLues) }));
      return a;
    };
    const n = affiches().length;
    return el("nav", { class: "nav", "aria-label": "Navigation" },
      marque("Flux", n > 1 ? `${n} serveurs` : (etat.compte.serveur || etat.info.nom || "")),
      lien("cameras"), lien("alertes"), droitPilotage() ? lien("pilotage") : null, lien("compte"),
      el("div", { class: "bas" },
        el("button", { class: "lien-nav", type: "button", onclick: feedback }, ic("message"), "Feedback"),
        el("div", { texte: `${etat.compte.prenom} ${etat.compte.nom}` })));
  }

  function majNavigation() {
    const nav = $(".nav");
    if (nav) nav.replaceWith(navigation());
  }

  function cadre(titre, sous, droite, contenu, retour = null) {
    return el("div", { class: "appli" }, navigation(),
      el("main", { class: "principal-zone" },
        el("header", { class: "entete" },
          retour ? el("a", { class: "btn-icone", href: retour, "aria-label": "Retour" }, ic("retour")) : null,
          el("div", { style: "min-width:0" }, el("h2", { texte: titre }),
            sous ? el("div", { class: "sous" }, sous) : null),
          el("div", { class: "droite" }, droite || [])),
        el("div", { class: "contenu" }, contenu)));
  }

  function afficher(vue, camera = null) {
    etat.vue = vue;
    etat.camera = camera;
    if (vue === "alertes") etat.nonLues = 0;
    if (vue === "cameras" && camera) return vueCamera(camera.srv, camera.id);
    ({ cameras: vueCameras, alertes: vueAlertes, pilotage: vuePilotage, compte: vueCompte })[vue]();
  }

  // Choix des serveurs affichés (tous, un ou plusieurs)
  function choixServeurs(surChange) {
    const connus = etat.serveurs.filter((s) => s.local || s.jeton);
    if (connus.length < 2) return null;
    const puce = (libelle, actif, onclick) => el("button", { class: `puce${actif ? " active" : ""}`, type: "button",
      "aria-pressed": String(actif), onclick }, libelle);
    const tous = connus.every((s) => s.affiche);
    return el("div", { class: "puces", role: "group", "aria-label": "Serveurs affichés" },
      puce("Tous les serveurs", tous, () => { connus.forEach((s) => { s.affiche = true; }); sauverServeurs(); surChange(); }),
      connus.map((s) => puce(s.nom, s.affiche && !tous, () => {
        if (tous) connus.forEach((x) => { x.affiche = x === s; });
        else { s.affiche = !s.affiche; if (!connus.some((x) => x.affiche)) s.affiche = true; }
        sauverServeurs(); surChange();
      })));
  }

  // --- caméras --------------------------------------------------------------------------------------------------------
  const ETATS = { direct: "En direct", alerte: "Alerte", chargement: "Démarrage…", arret: "Arrêtée" };

  function etiquetteEtat(cam) {
    const e = ETATS[cam.etat] ? cam.etat : "arret";
    return el("span", { class: `etiquette ${e}` }, el("span", { class: "point" }), ETATS[e]);
  }

  function rafraichirImage(img, srv, chemin) {
    // charge l'image suivante à côté, puis l'échange : pas de clignotement
    if (img.dataset.charge) return;
    img.dataset.charge = "1";
    const finir = (ok, url) => {
      delete img.dataset.charge;
      if (!ok) { img.hidden = true; img.nextSibling.hidden = false; return; }
      const ancienne = img.src;
      img.src = url; img.hidden = false; img.nextSibling.hidden = true;
      if (ancienne.startsWith("blob:")) URL.revokeObjectURL(ancienne);
    };
    if (srv.local) {
      const suivante = new Image();
      suivante.onload = () => finir(true, suivante.src);
      suivante.onerror = () => finir(false);
      suivante.src = `${API}${chemin}&t=${Date.now()}`;
    } else {
      urlImage(srv, `${chemin}&t=${Date.now()}`).then((u) => finir(true, u), () => finir(false));
    }
  }

  async function chargerCameras(srv) {
    const d = await api("cameras", { srv });
    srv.cameras = d.cameras.map((c) => ({ ...c, srv: srv.id }));
    srv.detection = d.detection;
    srv.entreprise = d.entreprise;
    srv.en_ligne = true;
    srv.erreur = "";
    if (srv.local && etat.compte.pilotage !== d.pilotage) { etat.compte.pilotage = d.pilotage; majNavigation(); }
    if (!srv.local && srv.compte) srv.compte.pilotage = d.pilotage;
    return d;
  }

  async function chargerToutes() {
    await Promise.all(affiches().map((s) => chargerCameras(s).catch((e) => {
      s.en_ligne = false; s.erreur = e.message; s.cameras = s.cameras || [];
    })));
    return affiches().flatMap((s) => (s.en_ligne ? s.cameras : []));
  }

  async function vueCameras() {
    const grille = el("div", { class: "grille" });
    const sous = el("span");
    const alertesSrv = el("div");
    const zone = el("div");
    monter(cadre("Caméras", sous, [], [zone, alertesSrv, grille]));
    const cartes = new Map();

    const filtre = choixServeurs(() => vueCameras());
    if (filtre) zone.append(filtre);

    function dessiner(cams) {
      const hs = affiches().filter((s) => !s.en_ligne);
      alertesSrv.replaceChildren(...hs.map((s) => el("div", { class: "msg erreur", texte: `${s.nom} : ${s.erreur || "injoignable"}` })));
      sous.textContent = cams.length ? `${cams.length} caméra(s)${plusieurs() ? ` · ${affiches().length} serveurs` : ""}` : "";
      if (!cams.length) {
        const ici = srvIci();
        grille.replaceChildren(el("div", { class: "vide", style: "grid-column:1/-1" }, ic("camera"), el("h3", { texte: "Aucune caméra" }),
          el("p", { texte: ici.entreprise === false && !plusieurs()
            ? "Votre compte n'est rattaché à aucune entreprise : demandez à votre responsable de vous en attribuer une."
            : "Aucune caméra n'est attribuée à votre entreprise pour l'instant." })));
        cartes.clear();
        return;
      }
      grille.querySelector(".vide")?.remove();
      const vus = new Set();
      for (const cam of cams) {
        const srv = srvPar(cam.srv);
        const cle = `${cam.srv}|${cam.id}`;
        vus.add(cle);
        let c = cartes.get(cle);
        if (!c) {
          const img = el("img", { alt: `Image de ${cam.nom}`, hidden: true, decoding: "async" });
          const rien = el("div", { class: "rien" }, ic("hors"), el("span", { texte: "Pas d'image" }));
          const etiq = el("span");
          const pers = el("span", { class: "etiquette droite" });
          const infos = el("span");
          const nomSrv = el("small", { class: "nom-serveur" });
          const carte = el("a", { class: "carte-cam", href: `#/camera/${encodeURIComponent(cam.srv)}/${encodeURIComponent(cam.id)}` },
            el("div", { class: "cadre-video" }, img, rien, etiq, pers),
            el("div", { class: "infos" }, el("div", { style: "min-width:0" }, el("strong", { texte: cam.nom }), nomSrv), infos));
          c = { carte, img, etiq, pers, infos, nomSrv };
          cartes.set(cle, c);
          grille.append(carte);
        }
        c.etiq.replaceWith(c.etiq = etiquetteEtat(cam));
        c.carte.classList.toggle("alerte", cam.etat === "alerte");
        c.pers.textContent = `${cam.personnes} pers.`;
        c.pers.hidden = cam.etat === "arret";
        c.nomSrv.textContent = plusieurs() ? srv.nom : "";
        c.infos.textContent = [cam.resolution, cam.fps ? `${cam.fps} i/s` : "", cam.detection ? "" : "sans détection"].filter(Boolean).join(" · ");
        if (cam.etat !== "arret") rafraichirImage(c.img, srv, `cameras/${cam.id}/image?largeur=640`);
        else { c.img.hidden = true; c.img.nextSibling.hidden = false; }
      }
      for (const [cle, c] of cartes) if (!vus.has(cle)) { c.carte.remove(); cartes.delete(cle); }
    }

    try { dessiner(await chargerToutes()); } catch (e) { if (e.code !== 401) toast(e.message, "", "erreur"); }
    repeter(async () => { try { dessiner(await chargerToutes()); } catch { /* réessaie au tour suivant */ } }, 2500);
  }

  async function vueCamera(idSrv, id) {
    const srv = srvPar(idSrv);
    let cam = srv && (srv.cameras || []).find((c) => c.id === id);
    if (srv && !cam) {
      try { await chargerCameras(srv); } catch { /* traité plus bas */ }
      cam = (srv.cameras || []).find((c) => c.id === id);
    }
    if (!cam) {
      monter(cadre("Caméra", "", [], el("div", { class: "vide" }, ic("hors"), el("h3", { texte: "Caméra introuvable" }),
        el("p", { texte: "Elle a été retirée ou n'est plus attribuée à votre entreprise." })), "#/cameras"));
      return;
    }
    const pilote = () => (srv.local ? etat.compte.pilotage : srv.compte?.pilotage);
    const largeur = Math.min(1920, Math.max(640, Math.round(innerWidth * (devicePixelRatio || 1) / 160) * 160));
    const chemin = `cameras/${id}/flux?largeur=${largeur}`;
    const video = el("img", { alt: `Vidéo en direct de ${cam.nom}`, "data-direct": "1" });
    const rien = el("div", { class: "rien", hidden: true }, ic("hors"), el("span", { texte: "Caméra arrêtée" }));
    let etiq = el("span");
    const cadreVideo = el("div", { class: "cadre-video" }, video, rien, etiq);
    const infos = el("span", { class: "sous" });
    const panneau = el("div");
    let directOuvert = false, arreterDirect = null;

    const echecDirect = () => { directOuvert = false; video.hidden = true; rien.hidden = false; };
    function ouvrirDirect() {
      if (cam.etat === "arret") {
        if (arreterDirect) { arreterDirect(); arreterDirect = null; }
        video.removeAttribute("src"); video.hidden = true; rien.hidden = false; directOuvert = false; return;
      }
      if (!directOuvert) {
        if (srv.local) video.src = `${API}${chemin}&t=${Date.now()}`;
        else { arreterDirect = lireDirectDistant(srv, chemin, video, echecDirect); arrets.push(() => arreterDirect && arreterDirect()); }
        directOuvert = true;
      }
      video.hidden = false; rien.hidden = true;
    }
    video.addEventListener("error", () => { if (srv.local) echecDirect(); });

    const plein = el("button", { class: "btn petit fantome", type: "button", onclick: () => {
      if (document.fullscreenElement) document.exitFullscreen(); else cadreVideo.requestFullscreen?.();
    } }, ic("plein"), "Plein écran");

    const dernieresAlertes = el("div", { class: "liste-alertes" }, el("span", { class: "roue petite" }));
    async function chargerDernieres() {
      try {
        const d = await api(`journal?limite=5&camera=${encodeURIComponent(id)}`, { srv });
        dernieresAlertes.replaceChildren(...(d.journal.length ? d.journal.map((l) => ligneAlerte({ ...l, srv: srv.id }, true))
          : [el("span", { style: "color:var(--texte2);font-size:14px", texte: "Aucune alerte récente." })]));
      } catch { dernieresAlertes.replaceChildren(); }
    }

    function dessiner() {
      etiq.replaceWith(etiq = etiquetteEtat(cam));
      infos.textContent = [cam.personnes ? `${cam.personnes} personne(s)` : cam.etat === "arret" ? "" : "Personne",
        cam.resolution, cam.fps ? `${cam.fps} i/s` : ""].filter(Boolean).join(" · ");
      ouvrirDirect();
      const pc = srv.pilotage && srv.pilotage.cameras.find((c) => c.id === id);
      const blocs = [el("div", { class: "panneau" }, el("h3", { texte: "En ce moment" }),
        el("div", { class: "stats" },
          el("div", { class: "stat" }, el("b", { texte: String(cam.personnes || 0) }), el("span", { texte: "personne(s) à l'image" })),
          el("div", { class: "stat" }, el("b", { texte: cam.fps ? String(cam.fps) : "—" }), el("span", { texte: "images / seconde" }))))];
      if (pilote() && pc) {
        blocs.push(el("div", { class: "panneau" }, el("h3", { texte: "Commandes" }),
          ligneReglage("Caméra en marche", "Démarre ou arrête la lecture de cette caméra.",
            inter(pc.en_marche, (v) => piloter(srv, "camera.marche", v, id), { libelle: "Caméra en marche" })),
          ligneReglage("Détection", "Analyse des personnes et alertes de cette caméra.",
            inter(pc.detection, (v) => piloter(srv, "camera.detection", v, id), { libelle: "Détection" })),
          el("div", { class: "boutons", style: "margin-top:12px" },
            el("button", { class: "btn petit", type: "button", disabled: !pc.en_marche, onclick: async (e) => {
              const b = e.currentTarget;
              b.disabled = true;
              try { await piloter(srv, "camera.clip", true, id); toast("Vidéo enregistrée sur le PC Flux", "Les secondes précédentes sont comprises.", "ok"); }
              catch (err) { toast(err.message, "", "erreur"); }
              finally { b.disabled = false; }
            } }, ic("video"), "Enregistrer une vidéo"))));
      }
      blocs.push(el("div", { class: "panneau" }, el("h3", { texte: "Dernières alertes" }), dernieresAlertes));
      panneau.replaceChildren(...blocs);
    }

    monter(cadre(cam.nom, plusieurs() ? srv.nom : "", [], el("div", { class: "vue" },
      el("div", {}, cadreVideo, el("div", { class: "barre-video" }, plein, infos)), panneau), "#/cameras"));
    if (pilote()) { try { srv.pilotage = await api("pilotage", { srv }); } catch { srv.pilotage = null; } }
    dessiner();
    chargerDernieres();
    repeter(async () => {
      try {
        await chargerCameras(srv);
        const n = srv.cameras.find((c) => c.id === id);
        if (!n) { location.hash = "#/cameras"; return; }
        cam = n;
        if (pilote()) srv.pilotage = await api("pilotage", { srv });
        dessiner();
      } catch { /* réessaie */ }
    }, 3000);
    repeter(chargerDernieres, 15000);
  }

  // vidéo en pause quand l'onglet est caché (le PC n'encode pas pour rien), reprise au retour
  document.addEventListener("visibilitychange", () => {
    document.querySelectorAll("img[data-direct]").forEach((i) => {
      if (i.src.startsWith("blob:")) return;  // vidéo d'un autre PC : la connexion reste ouverte
      if (document.hidden) { i.dataset.reprendre = i.getAttribute("src") || ""; i.removeAttribute("src"); }
      else if (i.dataset.reprendre) { i.src = i.dataset.reprendre.replace(/&t=\d+/, `&t=${Date.now()}`); delete i.dataset.reprendre; }
    });
  });

  // --- alertes -------------------------------------------------------------------------------------------------------
  function imagePhoto(l, attrs = {}) {
    const srv = srvPar(l.srv) || srvIci();
    const img = el("img", { alt: "", ...attrs });
    if (srv.local) img.src = `${API}journal/${l.id}/photo`;
    else urlImage(srv, `journal/${l.id}/photo`).then((u) => { img.src = u; }, () => { img.alt = "Photo indisponible"; });
    return img;
  }

  function voirPhoto(l) {
    const fermer = fenetre(el("figure", { style: "margin:0;text-align:center", onclick: () => fermer() },
      imagePhoto(l, { alt: `Photo de l'alerte : ${l.texte}` }),
      el("figcaption", { style: "color:#E7EEF8;margin-top:10px", texte: `${l.camera} · ${date(l.heure)}` })));
  }

  function ligneAlerte(l, compacte = false) {
    const srv = srvPar(l.srv);
    const vignette = el("button", { class: "vignette", type: "button", disabled: !l.photo, "aria-label": l.photo ? "Agrandir la photo" : null,
      onclick: () => voirPhoto(l) },
      l.photo ? imagePhoto(l, { loading: "lazy" }) : ic(l.niveau === "video" ? "video" : "image"));
    if (compacte) vignette.style.width = "84px";
    return el("div", { class: `alerte-ligne${l.prioritaire ? " prioritaire" : ""}` }, vignette,
      el("div", { class: "txt" }, el("b", { texte: l.texte }),
        el("div", { class: "meta" },
          el("span", { class: `niv ${l.niveau}`, texte: NOMS_NIVEAUX[l.niveau] || l.niveau }),
          compacte ? null : el("span", { texte: l.camera }),
          !compacte && plusieurs() && srv ? el("span", { class: "nom-serveur", texte: srv.nom }) : null,
          el("time", { datetime: new Date(l.heure * 1000).toISOString(), title: date(l.heure), texte: quand(l.heure) }))));
  }

  async function vueAlertes() {
    const liste = el("div", { class: "liste-alertes" });
    const plus = el("div", { class: "plus" });
    const choix = el("select", { "aria-label": "Caméra", onchange: () => { etat.filtreCamera = choix.value; recharger(); } },
      el("option", { value: "", texte: "Toutes les caméras" }));
    const notif = ("Notification" in window && Notification.permission === "default")
      ? el("button", { class: "btn petit fantome", type: "button", onclick: async (e) => {
        const b = e.currentTarget;
        const r = await Notification.requestPermission();
        b.remove();
        toast(r === "granted" ? "Notifications activées" : "Notifications refusées",
          r === "granted" ? "Vous serez prévenu même si cet onglet est en arrière-plan." : "", r === "granted" ? "ok" : "");
      } }, ic("cloche"), "Prévenir sur cet appareil") : null;
    const zone = el("div", { class: "filtres" }, choix);
    monter(cadre("Alertes", "", [notif], [choixServeurs(() => vueAlertes()), zone, liste, plus]));

    try { await chargerToutes(); } catch { /* la liste reste vide */ }
    for (const s of affiches()) for (const c of s.cameras || []) {
      choix.append(el("option", { value: `${s.id}|${c.id}`, texte: plusieurs() ? `${c.nom} · ${s.nom}` : c.nom }));
    }
    choix.value = [...choix.options].some((o) => o.value === etat.filtreCamera) ? etat.filtreCamera : "";
    const fins = new Map();  // serveur -> plus ancien identifiant chargé (pagination par serveur)

    async function charger(suite = false) {
      const [srvCam, idCam] = choix.value ? choix.value.split("|") : [null, null];
      const cibles = affiches().filter((s) => !srvCam || s.id === srvCam).filter((s) => !suite || fins.get(s.id) !== 0);
      const morceaux = await Promise.all(cibles.map(async (s) => {
        const p = new URLSearchParams({ limite: "30" });
        if (idCam) p.set("camera", idCam);
        if (suite && fins.get(s.id)) p.set("avant", fins.get(s.id));
        try {
          const d = await api(`journal?${p}`, { srv: s });
          fins.set(s.id, d.journal.length < 30 ? 0 : d.journal[d.journal.length - 1].id);
          return d.journal.map((l) => ({ ...l, srv: s.id }));
        } catch { fins.set(s.id, 0); return []; }
      }));
      return morceaux.flat().sort((a, b) => b.heure - a.heure);
    }
    function dessinerPlus() {
      const reste = [...fins.values()].some((v) => v);
      plus.replaceChildren(!reste || !etat.journal.length ? [] :
        el("button", { class: "btn", type: "button", texte: "Afficher plus", onclick: async (e) => {
          e.target.disabled = true;
          try {
            const suite = await charger(true);
            etat.journal.push(...suite);
            liste.append(...suite.map((l) => ligneAlerte(l)));
          } catch (err) { toast(err.message, "", "erreur"); }
          dessinerPlus();
        } }));
    }
    async function recharger() {
      liste.replaceChildren(el("div", { class: "vide" }, el("span", { class: "roue" })));
      fins.clear();
      try {
        etat.journal = await charger();
        liste.replaceChildren(...(etat.journal.length ? etat.journal.map((l) => ligneAlerte(l))
          : [el("div", { class: "vide" }, ic("alerte"), el("h3", { texte: "Aucune alerte" }),
            el("p", { texte: `Les alertes des ${etat.info.conservation_journal || 7} derniers jours apparaissent ici, en direct.` }))]));
      } catch (e) { liste.replaceChildren(el("div", { class: "msg erreur", texte: e.message })); }
      dessinerPlus();
    }
    await recharger();
    // les heures « il y a 3 min » restent justes
    repeter(() => liste.querySelectorAll("time").forEach((t) => { t.textContent = quand(Date.parse(t.dateTime) / 1000); }), 30000);
  }

  // écoute des nouvelles alertes de chaque serveur (attente longue, comme le service de notifications du téléphone)
  function ecouterAlertes() {
    const tour = ++etat.ecoute;
    for (const s of etat.serveurs) ecouterServeur(s, tour);
  }

  async function ecouterServeur(srv, tour) {
    let depuis = null;
    while (tour === etat.ecoute && etat.compte && (srv.local || srv.jeton) && etat.serveurs.includes(srv)) {
      try {
        const d = await api(depuis === null ? "alertes/attente" : `alertes/attente?depuis=${depuis}&delai=40`, { srv });
        if (tour !== etat.ecoute) return;
        if (depuis !== null && d.evenements.length) nouvellesAlertes(d.evenements.map((l) => ({ ...l, srv: srv.id })));
        depuis = d.dernier || 0;
      } catch (e) {
        if (e.code === 401) return;
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
  }

  function nouvellesAlertes(evenements) {
    const surAlertes = etat.vue === "alertes" && !document.hidden;
    const srv = srvPar(evenements[0].srv);
    if (srv && !srv.affiche) return;
    if (etat.vue === "alertes") {
      const liste = $(".contenu .liste-alertes");
      const filtre = etat.filtreCamera;
      const visibles = evenements.filter((l) => !filtre || `${l.srv}|${l.camera_id}` === filtre);
      if (liste && visibles.length) {
        if (!etat.journal.length) liste.replaceChildren();
        for (const l of visibles) {
          etat.journal.unshift(l);
          const n = ligneAlerte(l);
          n.classList.add("nouvelle");
          liste.prepend(n);
        }
      }
    }
    if (!surAlertes) {
      etat.nonLues += evenements.length;
      majNavigation();
    }
    for (const l of evenements.slice(-3)) {
      if (l.niveau !== "alerte" && !surAlertes) continue;
      const titre = plusieurs() && srv ? `${l.camera} · ${srv.nom}` : l.camera;
      if (!surAlertes) toast(titre, l.texte, "alerte", () => { location.hash = "#/alertes"; });
      if (document.hidden && "Notification" in window && Notification.permission === "granted") {
        try {
          const n = new Notification(`${l.prioritaire ? "⚠ " : ""}${titre}`, { body: l.texte, tag: `flux-${l.srv}-${l.id}`, icon: "icone.svg" });
          n.onclick = () => { window.focus(); location.hash = "#/alertes"; n.close(); };
        } catch { /* non disponible sur ce navigateur */ }
      }
    }
  }

  // --- pilotage --------------------------------------------------------------------------------------------------------
  async function piloter(srv, cle, valeur, camera = null) {
    const corps = { cle, valeur };
    if (camera) corps.camera = camera;
    srv.pilotage = await api("pilotage", { methode: "POST", corps, srv });
    return srv.pilotage;
  }

  function ligneReglage(titre, texte, controle, pile = false) {
    return el("div", { class: pile ? "reglage pile" : "reglage" }, el("div", { class: "txt" }, el("b", { texte: titre }), texte ? el("span", { texte }) : null), controle);
  }

  async function vuePilotage() {
    const pilotables = etat.serveurs.filter((s) => (s.local ? etat.compte.pilotage : s.compte?.pilotage) && (s.local || s.jeton));
    if (!pilotables.length) { location.hash = "#/cameras"; return; }
    let srv = pilotables.find((s) => s.id === etat.pilotageSrv) || pilotables[0];
    etat.pilotageSrv = srv.id;
    const zone = el("div", { class: "colonnes" }, el("div", { class: "vide" }, el("span", { class: "roue" })));
    const tous = el("input", { type: "checkbox", id: "p_tous" });
    const choix = pilotables.length > 1 ? el("div", { class: "filtres" },
      el("select", { "aria-label": "Serveur piloté", onchange: (e) => { etat.pilotageSrv = e.target.value; vuePilotage(); } },
        pilotables.map((s) => el("option", { value: s.id, texte: s.nom, selected: s === srv }))),
      el("label", { class: "case", style: "margin:0" }, tous, pilotables.length > 2 ? `Appliquer aussi aux ${pilotables.length - 1} autres serveurs` : "Appliquer aussi à l'autre serveur")) : null;
    monter(cadre("Pilotage", "Les changements s'appliquent tout de suite sur le PC Flux", [], [choix, zone]));

    // réglages généraux : sur ce serveur, et sur tous les serveurs pilotables si la case est cochée
    async function regler(cle, valeur) {
      await piloter(srv, cle, valeur);
      if (tous.checked) {
        const autres = pilotables.filter((s) => s !== srv);
        const res = await Promise.allSettled(autres.map((s) => piloter(s, cle, valeur)));
        const echecs = res.filter((r) => r.status === "rejected").length;
        if (echecs) toast(`${echecs} serveur(s) n'ont pas pu être modifiés`, "", "erreur");
      }
    }

    function dessiner() {
      const p = srv.pilotage;
      const niveau = el("select", { "aria-label": "Niveau de scan", onchange: async () => {
        niveau.disabled = true;
        try { await regler("detection.niveau", niveau.value); toast("Niveau de scan changé", "", "ok"); }
        catch (e) { toast(e.message, "", "erreur"); }
        dessiner();
      } }, p.niveaux.map((n) => el("option", { value: n.cle, texte: n.nom, selected: n.cle === p.niveau })));
      const texteNiveau = (p.niveaux.find((n) => n.cle === p.niveau) || {}).texte || "";

      const delai = (cle, titre, texte) => {
        const champ = el("input", { type: "number", min: 0, max: 1440, step: 1, value: Math.round(p.delais[cle] ?? 0),
          style: "width:96px;min-height:38px", "aria-label": titre });
        champ.addEventListener("change", async () => {
          const v = Number(champ.value);
          if (!(v >= 0 && v <= 1440)) { toast("Délai invalide", "Entre 0 et 1440 minutes.", "erreur"); return; }
          try { await regler(cle, v); toast(`${titre} : ${v} min`, "", "ok"); } catch (e) { toast(e.message, "", "erreur"); }
        });
        return ligneReglage(titre, texte, el("div", { class: "champ", style: "margin:0;display:flex;align-items:center;gap:6px" }, champ, "min"));
      };

      zone.replaceChildren(
        el("div", {},
          el("div", { class: "panneau" }, el("h3", { texte: "Aujourd'hui" }),
            el("div", { class: "stats" },
              el("div", { class: "stat" }, el("b", { texte: String(p.statistiques?.personnes ?? 0) }), el("span", { texte: "personnes" })),
              el("div", { class: "stat" }, el("b", { texte: String(p.statistiques?.actions_aujourdhui ?? 0) }), el("span", { texte: "actions" }))),
            p.calcul ? el("p", { style: "margin:12px 0 0;font-size:13px;color:var(--texte2)",
              texte: `Calcul : ${p.calcul}${p.carte_nvidia ? " (carte NVIDIA)" : ""}` }) : null),
          el("div", { class: "panneau" }, el("h3", { texte: "Détection" }),
            ligneReglage("Détection", "Toutes les caméras : analyse et alertes.",
              inter(p.detection, async (v) => { await regler("detection.actif", v); dessiner(); }, { libelle: "Détection" })),
            ligneReglage("Niveau de scan", texteNiveau, niveau, true))),
        el("div", {},
          el("div", { class: "panneau" }, el("h3", { texte: "Caméras" }),
            p.cameras.length ? p.cameras.map((c) => el("div", { class: "reglage" },
              el("div", { class: "txt" }, el("b", { texte: c.nom }), el("span", { texte: c.en_marche ? "En marche" : "Arrêtée" })),
              el("label", { style: "display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--texte2)" }, "Marche",
                inter(c.en_marche, async (v) => { await piloter(srv, "camera.marche", v, c.id); dessiner(); }, { libelle: `${c.nom} en marche` })),
              el("label", { style: "display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--texte2)" }, "Détection",
                inter(c.detection, async (v) => { await piloter(srv, "camera.detection", v, c.id); }, { libelle: `Détection de ${c.nom}` }))))
              : el("p", { style: "color:var(--texte2);margin:0", texte: "Aucune caméra attribuée." }))),
        el("div", {},
          el("div", { class: "panneau" }, el("h3", { texte: "Notifications" }),
            p.canaux.map((c) => ligneReglage(c.nom, c.configure ? "" : "À configurer d'abord dans Flux (Réglages › Notifications).",
              inter(c.actif, async (v) => { await regler(c.cle, v); }, { desactive: !c.configure && !c.actif, libelle: c.nom })))),
          el("div", { class: "panneau" }, el("h3", { texte: "Délais" }),
            delai("notif.delai", "Entre deux notifications", "Pour une même caméra."),
            delai("mail.delai", "Entre deux mails", ""))));
    }

    try {
      srv.pilotage = await api("pilotage", { srv });
      dessiner();
    } catch (e) {
      zone.replaceChildren(el("div", { class: "msg erreur", texte: e.message }));
      return;
    }
    repeter(async () => {
      if (document.activeElement && ["INPUT", "SELECT"].includes(document.activeElement.tagName)) return;
      try { srv.pilotage = await api("pilotage", { srv }); dessiner(); } catch { /* réessaie */ }
    }, 8000);
  }

  // --- compte ----------------------------------------------------------------------------------------------------------
  async function vueCompte() {
    const c = etat.compte;
    const zone = el("div", { class: "colonnes" });
    monter(cadre("Compte", c.mail, [el("button", { class: "btn petit fantome", type: "button", onclick: deconnecter }, ic("sortie"), "Se déconnecter")], zone));
    try { etat.compte = await api("compte"); } catch { return; }
    dessinerCompte(zone);
  }

  // Ajouter un autre PC Flux (même compte si possible)
  function ajouterServeur(existant = null) {
    const msg = el("div", { class: "msg", hidden: true });
    const montrer = (texte, genre = "erreur") => { msg.className = `msg ${genre}`; msg.textContent = texte; msg.hidden = !texte; };
    const champAdresse = el("input", { id: "s_adresse", placeholder: "192.168.1.30 ou 192.168.1.30:47810", required: true,
      value: existant ? existant.url.replace(/^https:\/\//, "") : "", autocapitalize: "none", spellcheck: false });
    const champMail = el("input", { id: "s_mail", type: "email", value: etat.compte.mail, required: true, autocomplete: "username" });
    const champMdp = el("input", { id: "s_mdp", type: "password", required: true, autocomplete: "current-password" });
    const lienCert = el("a", { class: "btn petit", target: "_blank", rel: "noopener", hidden: true }, ic("lien"), "Ouvrir pour accepter le certificat");
    const creer = el("div", { hidden: true });
    const bouton = el("button", { class: "btn principal", type: "submit", texte: existant ? "Se reconnecter" : "Ajouter le serveur" });
    let infoDistante = null;

    async function verifier(url) {
      const srv = { id: url, local: false, url, nom: url };
      try { infoDistante = await api("info", { srv, sansJeton: true }); return srv; }
      catch {
        lienCert.href = url; lienCert.hidden = false;
        montrer("Ce PC Flux ne répond pas encore à ce navigateur. Ouvrez son adresse dans un nouvel onglet, acceptez son certificat (« Avancé › Continuer »), fermez l'onglet puis réessayez. Vérifiez aussi que l'interface web est activée sur ce PC.", "info");
        return null;
      }
    }

    async function envoyer(e) {
      e.preventDefault();
      const url = normaliserAdresse(champAdresse.value);
      if (!url) return montrer("Adresse invalide.");
      if (url === `https://${location.host}` || (!existant && etat.serveurs.some((s) => s.url === url))) return montrer("Ce serveur est déjà dans la liste.");
      bouton.disabled = true;
      montrer("Connexion…", "info");
      try {
        const srv = await verifier(url);
        if (!srv) return;
        lienCert.hidden = true;
        const d = await api("connexion", { methode: "POST", srv, sansJeton: true, corps: { mail: champMail.value.trim(),
          mot_de_passe: champMdp.value, appareil: appareil(), version_app: `Web ${VERSION_WEB}` } });
        const nouveau = existant || { id: url, local: false, url, cameras: [], affiche: true };
        Object.assign(nouveau, { nom: infoDistante.nom || url, jeton: d.jeton, compte: d.compte, erreur: "", en_ligne: true });
        if (!d.compte.cgu_a_jour) await api("compte", { methode: "PATCH", srv: nouveau, corps: { cgu_version: infoDistante.cgu_version } }).catch(() => {});
        if (!existant) etat.serveurs.push(nouveau);
        sauverServeurs();
        fermer();
        toast(`${nouveau.nom} ajouté`, "Ses caméras apparaissent avec les autres.", "ok");
        ecouterServeur(nouveau, etat.ecoute);
        vueCompte();
      } catch (err) {
        if (err.code === 401 && infoDistante?.inscription) {
          montrer(`${err.message} Vous n'avez peut-être pas encore de compte sur « ${infoDistante.nom} ».`);
          creer.hidden = false;
        } else montrer(err.message, err.donnees?.statut === "attente" ? "info" : "erreur");
      } finally { bouton.disabled = false; }
    }

    // Pas de compte sur l'autre serveur : on le crée avec les mêmes informations (le responsable le valide)
    async function creerCompte() {
      if (!champMdp.value) return montrer("Indiquez le mot de passe que vous voulez utiliser sur ce serveur.");
      const url = normaliserAdresse(champAdresse.value);
      const srv = { id: url, local: false, url, nom: infoDistante?.nom || url };
      const c = etat.compte;
      const ok = await confirmer(`Créer votre compte sur « ${srv.nom} » ?`,
        `Avec les mêmes informations : ${c.prenom} ${c.nom}, ${champMail.value.trim()}${c.societe ? `, ${c.societe}` : ""}. Vous acceptez les conditions d'utilisation de ce serveur (version ${infoDistante.cgu_version}). Son responsable devra peut-être valider le compte.`,
        "Créer mon compte");
      if (!ok) return;
      try {
        const d = await api("inscription", { methode: "POST", srv, sansJeton: true, corps: { prenom: c.prenom, nom: c.nom,
          mail: champMail.value.trim(), societe: c.societe || c.entreprise || "", mot_de_passe: champMdp.value,
          cgu_version: infoDistante.cgu_version, appareil: appareil(), version_app: `Web ${VERSION_WEB}` } });
        creer.hidden = true;
        montrer(d.statut === "actif" ? "Compte créé : cliquez sur « Ajouter le serveur »." : d.message, d.statut === "actif" ? "ok" : "info");
      } catch (err) { montrer(err.message); }
    }
    creer.append(el("button", { class: "btn petit", type: "button", onclick: creerCompte }, ic("plus"), "Créer mon compte sur ce serveur avec mes informations"));

    const fermer = fenetre(el("form", { class: "fenetre", role: "dialog", "aria-modal": "true", style: "max-width:500px", onsubmit: envoyer },
      el("h3", { texte: existant ? `Se reconnecter à « ${existant.nom} »` : "Ajouter un autre PC Flux" }),
      el("p", { texte: "Ses caméras et ses alertes s'affichent avec celles de ce PC. Chaque PC garde ses propres comptes et ses propres droits. L'interface web doit y être activée (page FluxLite)." }),
      msg,
      el("div", { class: "champ" }, el("label", { for: "s_adresse", texte: "Adresse du PC Flux" }), champAdresse,
        el("div", { class: "aide", texte: "Celle affichée dans sa page FluxLite › Interface web." })),
      el("div", { class: "champ" }, el("label", { for: "s_mail", texte: "Adresse mail sur ce serveur" }), champMail),
      el("div", { class: "champ" }, el("label", { for: "s_mdp", texte: "Mot de passe sur ce serveur" }), champMdp,
        el("div", { class: "aide", texte: "Si votre responsable a transféré votre compte, c'est le même que sur ce PC." })),
      el("div", { class: "boutons", style: "justify-content:flex-start;margin-bottom:12px" }, lienCert, creer),
      el("div", { class: "boutons" },
        el("button", { class: "btn fantome", type: "button", texte: "Annuler", onclick: () => fermer() }), bouton)));
    (existant ? champMdp : champAdresse).focus();
  }

  function dessinerCompte(zone) {
    const c = etat.compte;
    const initiales = `${(c.prenom || "?")[0]}${(c.nom || "")[0] || ""}`.toUpperCase();

    // profil
    const msgProfil = el("div", { class: "msg", hidden: true });
    const formProfil = el("form", { onsubmit: async (e) => {
      e.preventDefault();
      try {
        etat.compte = await api("compte", { methode: "PATCH", corps: { prenom: $("#p_prenom").value.trim(), nom: $("#p_nom").value.trim() } });
        toast("Profil enregistré", "", "ok");
        dessinerCompte(zone);
        majNavigation();
      } catch (err) { msgProfil.className = "msg erreur"; msgProfil.textContent = err.message; msgProfil.hidden = false; }
    } }, msgProfil,
    el("div", { class: "ligne-champs" },
      el("div", { class: "champ" }, el("label", { for: "p_prenom", texte: "Prénom" }), el("input", { id: "p_prenom", value: c.prenom, required: true, maxlength: 60 })),
      el("div", { class: "champ" }, el("label", { for: "p_nom", texte: "Nom" }), el("input", { id: "p_nom", value: c.nom, required: true, maxlength: 60 }))),
    el("button", { class: "btn petit", type: "submit", texte: "Enregistrer" }));

    // mot de passe
    const msgMdp = el("div", { class: "msg", hidden: true });
    const formMdp = el("form", { onsubmit: async (e) => {
      e.preventDefault();
      const f = e.target;
      msgMdp.hidden = true;
      if ($("#m_nouveau", f).value !== $("#m_confirmer", f).value) {
        msgMdp.className = "msg erreur"; msgMdp.textContent = "Les deux nouveaux mots de passe ne sont pas identiques."; msgMdp.hidden = false; return;
      }
      try {
        const d = await api("compte/mot_de_passe", { methode: "POST", corps: { ancien: $("#m_ancien", f).value, nouveau: $("#m_nouveau", f).value } });
        f.reset();
        msgMdp.className = "msg ok"; msgMdp.textContent = d.message; msgMdp.hidden = false;
        etat.compte = await api("compte");
      } catch (err) { msgMdp.className = "msg erreur"; msgMdp.textContent = err.message; msgMdp.hidden = false; }
    } }, msgMdp,
    el("div", { class: "champ" }, el("label", { for: "m_ancien", texte: "Mot de passe actuel" }),
      el("input", { id: "m_ancien", type: "password", required: true, autocomplete: "current-password" })),
    el("div", { class: "ligne-champs" },
      el("div", { class: "champ" }, el("label", { for: "m_nouveau", texte: "Nouveau" }),
        el("input", { id: "m_nouveau", type: "password", required: true, minlength: 10, autocomplete: "new-password" })),
      el("div", { class: "champ" }, el("label", { for: "m_confirmer", texte: "Confirmer" }),
        el("input", { id: "m_confirmer", type: "password", required: true, minlength: 10, autocomplete: "new-password" }))),
    el("div", { class: "aide", style: "font-size:12.5px;color:var(--texte3);margin:-6px 0 12px", texte: "Au moins 10 caractères, avec au moins une lettre et un chiffre. Vos autres appareils seront déconnectés. Le mot de passe des autres serveurs ne change pas." }),
    el("button", { class: "btn petit", type: "submit", texte: "Changer le mot de passe" }));

    // sessions
    const revoquer = async (id) => {
      try { etat.compte = await api("compte/sessions/revoquer", { methode: "POST", corps: { id } }); dessinerCompte(zone); }
      catch (e) { toast(e.message, "", "erreur"); }
    };
    const sessions = c.sessions.map((s) => el("div", { class: "session" },
      el("div", { class: "txt" }, el("b", { texte: s.appareil || "Appareil inconnu" }),
        el("span", { texte: `${s.ip || ""} · active ${quand(s.activite)} · expire le ${date(s.expire_le)}` })),
      s.courante ? el("span", { class: "badge", texte: "Cet appareil" })
        : el("button", { class: "btn petit fantome", type: "button", texte: "Déconnecter", onclick: () => revoquer(s.id) })));

    // serveurs
    const lignesServeurs = etat.serveurs.map((s) => el("div", { class: "session" },
      el("div", { class: "txt" }, el("b", { texte: s.nom }),
        el("span", { texte: s.local ? `Ce PC · ${location.host}` : `${s.url.replace("https://", "")}${s.erreur ? ` · ${s.erreur}` : s.compte ? ` · ${s.compte.mail}` : ""}` })),
      s.local || s.jeton ? el("label", { style: "display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--texte2)" }, "Affiché",
        inter(s.affiche, async (v) => { s.affiche = v; if (!etat.serveurs.some((x) => x.affiche)) srvIci().affiche = true; sauverServeurs(); majNavigation(); }, { libelle: `Afficher ${s.nom}` })) : null,
      s.local ? null : (s.jeton ? null : el("button", { class: "btn petit", type: "button", texte: "Se reconnecter", onclick: () => ajouterServeur(s) })),
      s.local ? null : el("button", { class: "btn petit fantome danger", type: "button", texte: "Retirer", onclick: async () => {
        if (!await confirmer(`Retirer « ${s.nom} » ?`, "Ce navigateur ferme sa session sur ce serveur. Votre compte là-bas n'est pas supprimé.", "Retirer")) return;
        if (s.jeton) { try { await api("deconnexion", { methode: "POST", srv: s }); } catch { /* injoignable */ } }
        etat.serveurs = etat.serveurs.filter((x) => x !== s);
        sauverServeurs();
        dessinerCompte(zone);
        majNavigation();
      } })));

    const i = etat.info;
    zone.replaceChildren(
      el("div", {},
        el("div", { class: "panneau" },
          el("div", { class: "profil" }, el("div", { class: "avatar", texte: initiales }),
            el("div", {}, el("b", { texte: `${c.prenom} ${c.nom}` }), el("span", { texte: c.mail }))),
          el("dl", { class: "def" },
            el("dt", { texte: "Serveur" }), el("dd", { texte: c.serveur }),
            el("dt", { texte: "Entreprise" }), el("dd", { texte: c.entreprise || "Aucune (en attente d'attribution)" }),
            c.societe ? [el("dt", { texte: "Société indiquée" }), el("dd", { texte: c.societe })] : null,
            el("dt", { texte: "Pilotage" }), el("dd", { texte: c.pilotage ? "Autorisé" : "Non autorisé" }),
            el("dt", { texte: "Compte créé" }), el("dd", { texte: date(c.cree_le) }))),
        el("div", { class: "panneau" }, el("h3", { texte: "Mon profil" }), formProfil),
        el("div", { class: "panneau" }, el("h3", { texte: "Mot de passe" }), formMdp)),
      el("div", {},
        el("div", { class: "panneau" }, el("h3", { texte: "Serveurs Flux" }),
          el("p", { style: "margin:0 0 6px;color:var(--texte2);font-size:14px",
            texte: "Suivez plusieurs établissements depuis cette page : ajoutez leurs PC Flux. Chaque serveur garde ses propres comptes et ses propres droits." }),
          lignesServeurs,
          el("div", { class: "boutons", style: "margin-top:12px" },
            el("button", { class: "btn petit", type: "button", onclick: () => ajouterServeur() }, ic("plus"), "Ajouter un PC Flux"))),
        el("div", { class: "panneau" }, el("h3", { texte: "Appareils connectés à ce PC" }), sessions,
          c.sessions.length > 1 ? el("div", { class: "boutons", style: "margin-top:12px" },
            el("button", { class: "btn petit", type: "button", texte: "Déconnecter tous les autres", onclick: () => revoquer("autres") })) : null),
        el("div", { class: "panneau" }, el("h3", { texte: "Mes données (RGPD)" }),
          el("p", { style: "margin:0 0 12px;color:var(--texte2);font-size:14px",
            texte: `Responsable du traitement : ${(i.responsable || "").trim() || "l'entreprise qui exploite ce serveur"}${(i.contact || "").trim() ? ` · contact : ${i.contact.trim()}` : ""}. Les alertes sont effacées après ${i.conservation_journal || 7} jour(s).` }),
          el("div", { class: "boutons" },
            el("a", { class: "btn petit", href: `${API}compte/export`, download: "fluxlite-mes-donnees.json", texte: "Exporter mes données" }),
            el("button", { class: "btn petit fantome danger", type: "button", texte: "Supprimer mon compte", onclick: async () => {
              const mdp = await confirmer("Supprimer votre compte ?",
                "Votre compte et vos sessions seront effacés de ce serveur. Cette action est définitive.", "Supprimer", { danger: true, champMdp: true });
              if (mdp === null) return;
              try {
                const d = await api("compte", { methode: "DELETE", corps: { mot_de_passe: mdp } });
                etat.ecoute++;
                etat.compte = null;
                ecranConnexion(d.message, "ok");
              } catch (e) { toast(e.message, "", "erreur"); }
            } }))),
        el("div", { class: "panneau" }, el("h3", { texte: "À propos" }),
          el("dl", { class: "def" },
            el("dt", { texte: "Flux" }), el("dd", { texte: i.version_flux || "—" }),
            el("dt", { texte: "Interface web" }), el("dd", { texte: VERSION_WEB }),
            el("dt", { texte: "Conditions" }), el("dd", { texte: `version ${c.cgu_version || "—"}` })),
          el("p", { style: "margin:12px 0 0;color:var(--texte2);font-size:13px",
            texte: "Flux a été conçu et développé avec l'aide d'outils d'intelligence artificielle (assistant de programmation), sous la direction et la vérification de son auteur. Aucune donnée de ce PC n'est envoyée à un service d'IA." }),
          el("div", { class: "boutons", style: "margin-top:12px" },
            el("button", { class: "btn petit", type: "button", onclick: feedback }, ic("message"), "Feedback")))));
  }

  demarrer();
})();
