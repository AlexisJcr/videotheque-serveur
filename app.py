from flask import Flask, render_template, request, redirect, url_for, session, flash
import requests

app = Flask(__name__)
app.secret_key = "super_cle_secrete_videotheque"  # Nécessaire pour les sessions et messages flash

API_BASE_URL = "http://api:5000/api"

@app.route('/')
def index():
    search_query = request.args.get('q', '').lower()
    format_filter = request.args.get('format', '')
    
    try:
        response = requests.get(f"{API_BASE_URL}/films", timeout=5)
        films = response.json() if response.status_code == 200 else []
    except requests.exceptions.RequestException as e:
        flash(f"Erreur de communication avec l'API : {e}", "danger")
        films = []

    # Filtrage côté présentation (ou délégable à l'API)
    if search_query:
        films = [f for f in films if search_query in f.get('titre', '').lower() or search_query in f.get('realisateur', '').lower()]
    
    if format_filter == 'numerique':
        films = [f for f in films if f.get('supports', {}).get('numerique', {}).get('disponible')]
    elif format_filter in ['DVD', 'Blu-ray']:
        films = [
            f for f in films 
            if any(p.get('format') == format_filter for p in f.get('supports', {}).get('physiques', []))
        ]

    return render_template('catalogue.html', films=films, search_query=search_query, format_filter=format_filter)

@app.route('/film/<int:film_id>')
def detail_film(film_id):
    try:
        response = requests.get(f"{API_BASE_URL}/films", timeout=5)
        films = response.json() if response.status_code == 200 else []
        film = next((f for f in films if f.get('id') == film_id), None)
        if not film:
            flash("Film introuvable.", "warning")
            return redirect(url_for('index'))
        return render_template('detail.html', film=film)
    except requests.exceptions.RequestException as e:
        flash(f"Impossible de joindre l'API : {e}", "danger")
        return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        nom = request.form.get('nom')
        jeton = request.form.get('jeton')
        session['user_nom'] = nom
        session['jeton'] = jeton
        
        # Envoi d'un log vers l'API
        try:
            requests.post(f"{API_BASE_URL}/logs", json={
                "categorie": "AUTH",
                "action": "CONNEXION",
                "details": f"Connexion réussie de '{nom}' avec le jeton {jeton}",
                "auteur": nom
            }, timeout=3)
        except requests.exceptions.RequestException:
            pass

        flash(f"Connecté en tant que {nom} (Jeton actif : {jeton})", "success")
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    nom = session.get('user_nom', 'Anonyme')
    # Envoi d'un log vers l'API avant nettoyage de la session
    try:
        requests.post(f"{API_BASE_URL}/logs", json={
            "categorie": "AUTH",
            "action": "DECONNEXION",
            "details": f"Déconnexion du membre '{nom}'",
            "auteur": nom
        }, timeout=3)
    except requests.exceptions.RequestException:
        pass

    session.clear()
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for('index'))

@app.route('/emprunter', methods=['POST'])
def emprunter():
    support_id = request.form.get('supportId')
    film_id = request.form.get('filmId')
    jeton = session.get('jeton')

    if not jeton:
        flash("Refusé (401) : Connectez-vous avec un jeton valide pour emprunter.", "danger")
        return redirect(url_for('login'))

    try:
        # Appel POST vers l'API avec le payload attendu dans le diagramme de séquence
        resp = requests.post(
            f"{API_BASE_URL}/emprunt",
            json={"supportId": support_id, "jeton": jeton},
            timeout=5
        )
        data = resp.json()
        
        if resp.status_code in [200, 201]:
            retour_prevu = data.get('date_retour_prevue', 'J+14')
            flash(f"Emprunt confirmé pour le support {support_id} ! Retour prévu le : {retour_prevu}", "success")
        else:
            # Affiche le message métier renvoyé par l'API (RG3, RG4, RG5...)
            erreur_msg = data.get('erreur', 'Erreur lors de l\'emprunt.')
            flash(f"Échec ({resp.status_code}) : {erreur_msg}", "danger")
            
    except requests.exceptions.RequestException:
        flash("La route /api/emprunt n'est pas encore active côté API ou l'API est hors-ligne.", "warning")

    return redirect(url_for('detail_film', film_id=film_id) if film_id else url_for('index'))

@app.route('/restituer', methods=['POST'])
def restituer():
    support_id = request.form.get('supportId')
    film_id = request.form.get('filmId')
    try:
        resp = requests.post(f"{API_BASE_URL}/retour", json={"supportId": support_id}, timeout=5)
        if resp.status_code == 200:
            flash(f"Support {support_id} restitué avec succès !", "success")
        else:
            flash(f"Erreur lors du retour : {resp.json().get('erreur', 'Erreur inconnue')}", "danger")
    except requests.exceptions.RequestException:
        flash("La route /api/retour n'est pas encore codée côté API.", "warning")

    return redirect(url_for('detail_film', film_id=film_id) if film_id else url_for('index'))

@app.route('/admin/ajouter', methods=['GET', 'POST'])
def admin_ajouter():
    if not session.get('jeton'):
        flash("Accès refusé : vous devez être connecté pour administrer le catalogue.", "danger")
        return redirect(url_for('login'))

    if request.method == 'POST':
        nouveau_film = {
            "titre": request.form.get('titre'),
            "realisateur": request.form.get('realisateur'),
            "annee": int(request.form.get('annee', 2026)),
            "genre": request.form.get('genre'),
            "synopsis": request.form.get('synopsis'),
            "supports": {
                "numerique": {
                    "disponible": request.form.get('num_dispo') == 'on'
                },
                "physiques": []
            }
        }
        # Ajout d'un premier exemplaire physique si renseigné
        sup_id = request.form.get('support_id')
        sup_format = request.form.get('support_format')
        if sup_id and sup_format:
            nouveau_film["supports"]["physiques"].append({
                "supportId": sup_id,
                "format": sup_format,
                "etat": "DISPONIBLE"
            })

        try:
            resp = requests.post(f"{API_BASE_URL}/films", json=nouveau_film, timeout=5)
            if resp.status_code in [200, 201]:
                flash("Film ajouté au catalogue avec succès !", "success")
                return redirect(url_for('index'))
            else:
                flash(f"Erreur API ({resp.status_code}) lors de l'ajout.", "danger")
        except requests.exceptions.RequestException:
            flash("La route POST /api/films n'est pas encore implémentée côté API.", "warning")

    return render_template('admin.html')


# ==== Supprimer un film ====
@app.route('/admin/supprimer/<int:film_id>', methods=['POST'])
def admin_supprimer(film_id):
    if not session.get('jeton'):
        flash("Accès refusé : vous devez être connecté pour administrer le catalogue.", "danger")
        return redirect(url_for('login'))

    try:
        resp = requests.delete(f"{API_BASE_URL}/films/{film_id}", timeout=5)
        if resp.status_code == 200:
            flash("Film supprimé avec succès du catalogue.", "success")
        else:
            flash("Erreur API lors de la suppression.", "danger")
    except requests.exceptions.RequestException:
        flash("Impossible de joindre l'API pour la suppression.", "danger")
    
    return redirect(url_for('index'))


# ==== Modification d'un film ====
@app.route('/admin/modifier/<int:film_id>', methods=['GET', 'POST'])
def admin_modifier(film_id):
    if not session.get('jeton'):
        flash("Accès refusé : vous devez être connecté pour administrer le catalogue.", "danger")
        return redirect(url_for('login'))

    # Traitement du formulaire soumis
    if request.method == 'POST':
        donnees_maj = {
            "titre": request.form.get('titre'),
            "realisateur": request.form.get('realisateur'),
            "annee": int(request.form.get('annee')),
            "genre": request.form.get('genre'),
            "synopsis": request.form.get('synopsis'),
            "supports": {
                "numerique": {
                    "disponible": request.form.get('num_dispo') == 'on'
                }
            }
        }
        try:
            resp = requests.put(f"{API_BASE_URL}/films/{film_id}", json=donnees_maj, timeout=5)
            if resp.status_code == 200:
                flash("Film modifié avec succès !", "success")
                return redirect(url_for('detail_film', film_id=film_id))
        except requests.exceptions.RequestException:
            flash("Erreur de connexion à l'API.", "danger")
        return redirect(url_for('detail_film', film_id=film_id))

    # Méthode GET : Récupérer le film pour pré-remplir le formulaire
    try:
        resp = requests.get(f"{API_BASE_URL}/films/{film_id}", timeout=5)
        if resp.status_code == 200:
            film = resp.json()
            return render_template('admin_edit.html', film=film)
    except requests.exceptions.RequestException:
        pass
    
    flash("Impossible de récupérer les données du film.", "danger")
    return redirect(url_for('index'))


# =============================
# === Ajout d'un exemplaire ===
# =============================
@app.route('/admin/ajouter_support/<int:film_id>', methods=['POST'])
def admin_ajouter_support(film_id):
    if not session.get('jeton'):
        flash("Accès refusé : vous devez être connecté pour administrer le catalogue.", "danger")
        return redirect(url_for('login'))

    nouveau_support = {
        "supportId": request.form.get('supportId'),
        "format": request.form.get('format')
    }
    try:
        resp = requests.post(f"{API_BASE_URL}/films/{film_id}/supports", json=nouveau_support, timeout=5)
        if resp.status_code == 201:
            flash(f"L'exemplaire {nouveau_support['supportId']} a été ajouté au stock !", "success")
        else:
            flash("Erreur lors de l'ajout du support.", "danger")
    except requests.exceptions.RequestException:
        flash("Impossible de joindre l'API REST.", "danger")
        
    return redirect(url_for('detail_film', film_id=film_id))


# ====================================
# === Modification d'un exemplaire ===
# ====================================
@app.route('/admin/modifier_support/<int:film_id>/<support_id>', methods=['POST'])
def admin_modifier_support(film_id, support_id):
    if not session.get('jeton'):
        flash("Action requérant une authentification.", "danger")
        return redirect(url_for('login'))
        
    donnees_maj = {
        "format": request.form.get('format'),
        "etat": request.form.get('etat'),
        "nouveau_supportId": request.form.get('nouveau_supportId')
    }
    
    try:
        resp = requests.put(f"{API_BASE_URL}/films/{film_id}/supports/{support_id}", json=donnees_maj, timeout=5)
        if resp.status_code == 200:
            flash(f"Support mis à jour !", "success")
        else:
            flash(f"Erreur API : {resp.json().get('erreur')}", "danger")
    except requests.exceptions.RequestException:
        flash("Connexion à l'API impossible.", "danger")
        
    return redirect(url_for('detail_film', film_id=film_id))


# ===================================
# === Suppression d'un exemplaire ===
# ===================================
@app.route('/admin/supprimer_support/<int:film_id>/<support_id>', methods=['POST'])
def admin_supprimer_support(film_id, support_id):
    if not session.get('jeton'):
        flash("Action requérant une authentification.", "danger")
        return redirect(url_for('login'))
        
    try:
        resp = requests.delete(f"{API_BASE_URL}/films/{film_id}/supports/{support_id}", timeout=5)
        if resp.status_code == 200:
            flash(f"Le support {support_id} a été supprimé du stock.", "success")
        else:
            # Affichera l'erreur 403 de l'API si le support est prêté
            flash(f"Refusé : {resp.json().get('erreur')}", "warning")
    except requests.exceptions.RequestException:
        flash("Connexion à l'API impossible.", "danger")
        
    return redirect(url_for('detail_film', film_id=film_id))



# =======================
# === Système de logs ===
# =======================

@app.route('/admin/logs')
def admin_logs():
    # Protection : accessible uniquement si connecté avec jeton
    if not session.get('jeton'):
        flash("Accès réservé aux administrateurs connectés.", "danger")
        return redirect(url_for('login'))

    filtre_cat = request.args.get('categorie', '')
    
    try:
        resp = requests.get(f"{API_BASE_URL}/logs", timeout=5)
        logs = resp.json() if resp.status_code == 200 else []
    except requests.exceptions.RequestException:
        flash("Impossible de joindre le service de logs de l'API.", "danger")
        logs = []

    if filtre_cat:
        logs = [l for l in logs if l.get('categorie') == filtre_cat]

    return render_template('admin_logs.html', logs=logs, filtre_cat=filtre_cat)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)