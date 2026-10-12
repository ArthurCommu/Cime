# Champs de l'instantané : ce que la page en fait

Ce que la page fait de chaque champ de l'instantané d'état. Une ligne par champ ; `test_champs_etat.py` exige que chaque champ de la table existe dans l'exemple d'état et que chaque champ « affiché » soit lu dans le JS de la page.

| champ | sort | où / pourquoi |
|---|---|---|
| `version` | affiché | pied de page : « instantané v… » |
| `genere_a` | affiché | pied de page et bandeau : âge de l'instantané (fraîcheur, niveau ok/ambre/rouge) |
| `duree_collecte_ms` | affiché | pied de page : « collecté en … ms » |
| `projet` | affiché | conteneur ; ses sous-champs sont détaillés ci-dessous |
| `projet.nom` | affiché | en-tête (h1), titre de l'onglet, page d'équipe |
| `projet.racine` | écarté | technique : chemin absolu du projet, aucun écran ne le montre |
| `projet.prefixe` | écarté | technique : préfixe des sessions tmux, sert à l'hôte |
| `projet.branche_reference` | affiché | page d'équipe : « à jour sur … » / « … de retard sur … » |
| `projet.etapes` | affiché | Supervision, section « Avancement du projet » : les étapes, faite / prochaine / à venir |
| `projet.etapes[].nom` | affiché | Supervision, avancement : libellé de l'étape |
| `projet.etapes[].atteinte` | affiché | Supervision, avancement : étape faite / prochaine / à venir |
| `projet.etapes[].date` | affiché | Supervision, avancement : date courte de l'étape |
| `sources` | affiché | bandeau d'en-tête et vue d'ensemble : sources en échec |
| `sources[].nom` | affiché | bandeau d'en-tête : nom de la source en échec ; rend « inconnu » les mesures qui en dépendent |
| `sources[].ok` | affiché | bandeau d'en-tête : filtre des sources en échec (ok === false) |
| `agents` | affiché | organigramme, cartes d'agents |
| `agents[].id` | affiché | organigramme, carte d'agent : nom ; liens vers le fil et choix du terminal |
| `agents[].role` | affiché | organigramme : rangement par rôle (assistant, coordinateur, worker) |
| `agents[].equipe` | affiché | organigramme et page d'équipe : agents rattachés à l'équipe |
| `agents[].parent` | écarté | technique : la hiérarchie se déduit de role + equipe, parent n'est pas lu |
| `agents[].session_tmux` | affiché | carte d'agent : « session absente (…) » ; terminal : agents avec session |
| `agents[].vivant` | affiché | carte d'agent : session absente / inconnue (null) ; agents arrêtés de la vue d'ensemble |
| `agents[].etat` | affiché | carte d'agent : pastille et mot d'état |
| `agents[].etat_depuis` | affiché | carte d'agent : « depuis … » |
| `agents[].etat_source` | affiché | carte d'agent : origine de l'état, en discret |
| `agents[].tache` | affiché | carte d'agent : ligne de tâche en cours |
| `agents[].derniere_phrase` | affiché | carte d'agent : fin de la dernière phrase quand l'agent ne travaille pas |
| `agents[].modele` | affiché | carte d'agent : nom du modèle |
| `agents[].contexte` | affiché | carte d'agent : barre de contexte |
| `agents[].contexte.tokens` | affiché | carte d'agent, barre de contexte : tokens utilisés et pourcentage |
| `agents[].contexte.limite` | affiché | carte d'agent, barre de contexte : limite et pourcentage |
| `agents[].contexte.source` | écarté | technique : provenance de la mesure de contexte, pas montrée |
| `agents[].cout_usd_estime` | affiché | carte d'agent : « ≈ … $ » (ou « inconnu » si null) |
| `agents[].consommation` | affiché | carte d'agent : ligne « conso 15 min · 60 min » ; « conso inconnue » si null ; rien pour l'utilisateur ; page d'équipe : grille détaillée |
| `agents[].consommation.15min` | affiché | carte d'agent : « conso 15 min : … lus » ; page d'équipe : colonne 15 min de la grille |
| `agents[].consommation.15min.lus` | affiché | carte d'agent : jetons lus sur 15 min ; page d'équipe : grille |
| `agents[].consommation.15min.ecrits` | affiché | page d'équipe, grille 15 min : jetons écrits |
| `agents[].consommation.15min.tours` | affiché | page d'équipe, grille 15 min : nombre de tours |
| `agents[].consommation.15min.contexte_moyen` | affiché | page d'équipe, grille 15 min : contexte moyen (« inconnu » si null, jamais 0) |
| `agents[].consommation.15min.dont_sous_agents` | affiché | carte d'agent : « (dont … sous-agents) », seulement si la valeur est supérieure à 0 |
| `agents[].consommation.60min` | affiché | carte d'agent : « 60 min : … lus » ; page d'équipe : colonne 60 min de la grille |
| `agents[].consommation.60min.lus` | affiché | carte d'agent : jetons lus sur 60 min ; page d'équipe : grille |
| `agents[].consommation.60min.ecrits` | affiché | page d'équipe, grille 60 min : jetons écrits |
| `agents[].consommation.60min.tours` | affiché | page d'équipe, grille 60 min : nombre de tours |
| `agents[].consommation.60min.contexte_moyen` | affiché | page d'équipe, grille 60 min : contexte moyen (« inconnu » si null, jamais 0) |
| `agents[].consommation.60min.dont_sous_agents` | écarté | la carte ne montre la part des sous-agents que sur 15 min |
| `agents[].consommation.source` | écarté | technique : `transcript` ou `transcript:cwd`, provenance de la mesure, pas montrée |
| `agents[].brouillon` | affiché | page d'équipe : encart « Brouillon resté dans le terminal » |
| `equipes` | affiché | vue d'ensemble (organigramme), page d'équipe, archives |
| `equipes[].nom` | affiché | vue d'ensemble, page d'équipe, archives : nom de l'équipe |
| `equipes[].mission` | affiché | vue d'ensemble, page d'équipe, archives : phrase de mission |
| `equipes[].speciale` | affiché | page d'équipe : mention « équipe spéciale · à la demande » |
| `equipes[].statut` | affiché | vue d'ensemble : équipes actives ; archives : équipes terminées ; page d'équipe : clôture |
| `equipes[].cloturee_le` | affiché | archives : « Clôturée le … » (à défaut, « vers le » dernier échange du fil) |
| `equipes[].branche` | affiché | page d'équipe et archives : branche |
| `equipes[].commit` | affiché | page d'équipe et archives : commit de la branche |
| `equipes[].worktree` | écarté | technique : chemin absolu du worktree, aucun écran ne le montre |
| `equipes[].avancement` | affiché | vue d'ensemble, page d'équipe, archives : barre d'avancement |
| `equipes[].avancement.faites` | affiché | page d'équipe, archives : « n faites » et barre |
| `equipes[].avancement.en_cours` | affiché | page d'équipe, archives : « n en cours » et barre |
| `equipes[].avancement.a_faire` | affiché | page d'équipe, archives : « n à faire » et barre |
| `equipes[].fichiers_touches` | affiché | page d'équipe : liste des fichiers touchés ; archives : compte |
| `equipes[].perimetre_declare` | affiché | page d'équipe : périmètre déclaré |
| `equipes[].hors_perimetre` | affiché | page d'équipe : fichiers touchés marqués hors périmètre |
| `equipes[].retard_sur_base` | affiché | page d'équipe : « à jour sur … » / « n commits de retard » |
| `equipes[].depend_de` | affiché | page d'équipe : « dépend de » et « alimente » ; graphe des dépendances |
| `fil` | affiché | page « Fil des échanges », vue d'ensemble, page d'équipe |
| `fil[].id` | affiché | fil : clé de dépliage et de relecture du texte complet |
| `fil[].horodatage` | affiché | fil : âge de l'échange ; attente depuis |
| `fil[].de` | affiché | fil : expéditeur (« de → à ») |
| `fil[].a` | affiché | fil : destinataire (« de → à ») |
| `fil[].nature` | affiché | fil : étiquette de nature (ou « conversation » pour un hook) |
| `fil[].resume` | affiché | fil : ligne de résumé de l'échange |
| `fil[].fichier` | affiché | fil, échange déplié : chemin du fichier et texte complet |
| `fil[].en_attente` | affiché | fil : « attend … depuis … » ; seuil des questions sans réponse |
| `fil[].non_lu` | affiché | fil : repère « non lu » et bouton « Marquer comme lu » (action `lu`, `attente_id` = `msg-<n>`) ; absent des attentes et des compteurs |
| `fil[].source` | affiché | fil : distingue la conversation utilisateur ↔ Assistant (source hook) |
| `fil[].etat_livraison` | écarté | état de livraison, non montré par la page |
| `fil[].preuve` | écarté | objet de la dernière transition, non montré par la page |
| `attentes_utilisateur` | affiché | rail de la scène, « Ce qui t'attend » (les trois plus anciennes ; le détail d'une équipe montre les siennes) ; compteur de l'en-tête |
| `attentes_utilisateur[].id` | affiché | « Ce qui t'attend » : identifiant de l'action en cours / envoyée |
| `attentes_utilisateur[].nature` | affiché | « Ce qui t'attend » : étiquette et choix des boutons |
| `attentes_utilisateur[].titre` | affiché | « Ce qui t'attend » : titre de la carte |
| `attentes_utilisateur[].bloque` | affiché | « Ce qui t'attend » : « bloque : … » |
| `attentes_utilisateur[].depuis` | affiché | « Ce qui t'attend » : ordre d'attente et « nouveau depuis la dernière visite » |
| `attentes_utilisateur[].agent` | affiché | « Ce qui t'attend » : « demandé par … » ; clôture sur la page d'équipe |
| `attentes_utilisateur[].equipe` | affiché | « Ce qui t'attend » : « équipe … » avec lien vers la page de l'équipe (rien si null) ; clôture : équipe visée |
| `attentes_utilisateur[].actions` | écarté | la page déduit les boutons de nature ; la liste actions n'est pas lue |
| `consommation` | affiché | Supervision, section « Consommation » après Avancement ; null → « inconnue » avec la source `transcripts` en échec |
| `consommation.15min` | affiché | section « Consommation » : le grand chiffre (jetons lus) et le nombre de tours |
| `consommation.15min.lus` | affiché | section « Consommation » : le grand chiffre, jetons lus sur 15 min (« inconnu » si absent, jamais 0) |
| `consommation.15min.ecrits` | écarté | la section compacte ne montre plus les jetons écrits (le détail par agent reste dans la carte de l'agent) |
| `consommation.15min.tours` | affiché | section « Consommation » : « n tours » sous le grand chiffre |
| `consommation.60min` | affiché | section « Consommation » : « X sur 60 min » sous le grand chiffre |
| `consommation.60min.lus` | affiché | section « Consommation » : jetons lus sur 60 min |
| `consommation.60min.ecrits` | écarté | la section compacte ne montre plus les jetons écrits |
| `consommation.60min.tours` | écarté | la section compacte ne montre que les tours des 15 dernières minutes |
| `consommation.gros_postes` | affiché | section « Consommation » : les trois plus gros postes ; liste vide → « aucune consommation sur 15 min » |
| `consommation.gros_postes[].agent` | affiché | gros postes : nom de l'agent |
| `consommation.gros_postes[].lus_15min` | affiché | gros postes : jetons lus sur 15 min, à droite de la barre |
| `consommation.gros_postes[].part_15min` | affiché | gros postes : part du projet, largeur de la barre en couleur neutre (inconnue → « part inconnue », pas de barre) |
| `alarmes` | affiché | vue d'ensemble, carte d'agent, page d'équipe : alarmes |
| `alarmes[].id` | écarté | technique : identifiant stable de l'alarme, pas montré |
| `alarmes[].type` | affiché | carte d'alarme : libellé du type ; recouvrement du graphe |
| `alarmes[].gravite` | affiché | carte d'alarme : couleur et mot de gravité ; agent en rouge |
| `alarmes[].agents` | affiché | carte d'alarme : liens vers le fil ; alarmes rattachées à la carte d'agent |
| `alarmes[].equipes` | affiché | carte d'alarme : liens vers la page d'équipe ; arêtes rouges du graphe |
| `alarmes[].depuis` | affiché | carte d'alarme : « depuis … » ; alarmes nouvelles de la vue d'ensemble |
| `alarmes[].mesure` | affiché | carte d'alarme : ligne « Mesure » |
| `alarmes[].quoi_faire` | affiché | carte d'alarme : ligne « Quoi faire » |
| `equipes[].en_avance_sur_base` | affiché | page d'équipe, en-tête, « Avance sur la base » : 0 → « rien d’avance sur <base> », N → « N commits pas encore dans <base> », null → « pas de branche » ou « inconnu » ; jamais une alarme |
| `sessions_hors_organigramme` | affiché | vue d'ensemble, section « Sessions hors organigramme » après Alarmes ; absente si liste vide ; null → « inconnues » avec la source `tmux` en échec |
| `sessions_hors_organigramme[].nom` | affiché | section « Sessions hors organigramme » : nom de la session, en mono |
| `sessions_hors_organigramme[].depuis` | affiché | section « Sessions hors organigramme » : « ouverte il y a … » |
| `sessions_hors_organigramme[].activite` | affiché | section « Sessions hors organigramme » : « activité il y a … » |
| `decisions_recentes` | écarté | retirées de Supervision : la page ne les affiche plus |
| `decisions_recentes[].date` | écarté | retirées de Supervision avec la section « Décisions récentes » |
| `decisions_recentes[].titre` | écarté | retirées de Supervision avec la section « Décisions récentes » |
| `agents[].dettes` | écarté | champ `dettes` de `agents`, non montré par la page |
| `agents[].dettes[].attendu` | écarté | champ `attendu` de `agents`, non montré par la page |
| `agents[].dettes[].de` | écarté | champ `de` de `agents`, non montré par la page |
| `agents[].dettes[].depuis` | écarté | champ `depuis` de `agents`, non montré par la page |
| `agents[].dettes[].id` | écarté | champ `id` de `agents`, non montré par la page |
| `agents[].dettes[].objet` | écarté | champ `objet` de `agents`, non montré par la page |
| `agents[].file` | écarté | champ `file` de `agents`, non montré par la page |
| `agents[].file[].de` | écarté | champ `de` de `agents`, non montré par la page |
| `agents[].file[].depuis` | écarté | champ `depuis` de `agents`, non montré par la page |
| `agents[].file[].id` | écarté | champ `id` de `agents`, non montré par la page |
| `agents[].file[].nature` | écarté | champ `nature` de `agents`, non montré par la page |
| `agents[].file[].objet` | écarté | champ `objet` de `agents`, non montré par la page |
| `agents[].file[].resume` | écarté | champ `resume` de `agents`, non montré par la page |
| `agents[].occupe_par` | écarté | champ `occupe_par` de `agents`, non montré par la page |
| `alarmes[].destinataire` | écarté | champ `destinataire` de `alarmes`, non montré par la page |
| `aretes` | écarté | activité par couple de/à ; non montré par la page |
| `aretes[].a` | écarté | champ `a` de `aretes`, non montré par la page |
| `aretes[].de` | écarté | champ `de` de `aretes`, non montré par la page |
| `aretes[].en_file` | écarté | champ `en_file` de `aretes`, non montré par la page |
| `aretes[].livre` | écarté | champ `livre` de `aretes`, non montré par la page |
| `aretes[].ouvertes` | écarté | champ `ouvertes` de `aretes`, non montré par la page |
| `aretes[].total_15min` | écarté | champ `total_15min` de `aretes`, non montré par la page |
| `attentes_utilisateur[].message_id` | écarté | champ `message_id` de `attentes_utilisateur`, non montré par la page |
| `attentes_utilisateur[].objet` | écarté | champ `objet` de `attentes_utilisateur`, non montré par la page |
| `facteur` | écarté | battement du facteur ; non montré par la page |
| `facteur.age_s` | écarté | champ `age_s` de `facteur`, non montré par la page |
| `facteur.arrete` | écarté | champ `arrete` de `facteur`, non montré par la page |
| `facteur.battement` | écarté | champ `battement` de `facteur`, non montré par la page |
| `fil[].preuve.voie` | écarté | champ `voie` de `fil`, non montré par la page |
| `flux` | écarté | les 200 dernières requêtes ; la page ne les lit pas dans l'instantané, elle lit `GET /api/flux?depuis=` |
| `flux[].a` | écarté | champ `a` de `flux`, non montré par la page |
| `flux[].de` | écarté | champ `de` de `flux`, non montré par la page |
| `flux[].debiteur` | écarté | champ `debiteur` de `flux`, non montré par la page |
| `flux[].echeance` | écarté | champ `echeance` de `flux`, non montré par la page |
| `flux[].etat` | écarté | champ `etat` de `flux`, non montré par la page |
| `flux[].id` | écarté | champ `id` de `flux`, non montré par la page |
| `flux[].nature` | écarté | champ `nature` de `flux`, non montré par la page |
| `flux[].objet` | écarté | champ `objet` de `flux`, non montré par la page |
| `flux[].resume` | écarté | champ `resume` de `flux`, non montré par la page |
| `flux[].transitions` | écarté | champ `transitions` de `flux`, non montré par la page |
| `flux[].transitions[].auteur` | écarté | champ `auteur` de `flux`, non montré par la page |
| `flux[].transitions[].etat` | écarté | champ `etat` de `flux`, non montré par la page |
| `flux[].transitions[].horodatage` | écarté | champ `horodatage` de `flux`, non montré par la page |
| `flux[].transitions[].voie` | écarté | champ `voie` de `flux`, non montré par la page |
| `ordres` | écarté | ordres du facteur ; non montré par la page |
| `ordres[].auteur` | écarté | champ `auteur` de `ordres`, non montré par la page |
| `ordres[].cible` | écarté | champ `cible` de `ordres`, non montré par la page |
| `ordres[].etat` | écarté | champ `etat` de `ordres`, non montré par la page |
| `ordres[].id` | écarté | champ `id` de `ordres`, non montré par la page |
| `ordres[].verbe` | écarté | champ `verbe` de `ordres`, non montré par la page |
| `agents[].brouillon.depuis` | affiché | page d'équipe, carte d'agent : « Brouillon resté dans le terminal · depuis … » |
| `agents[].brouillon.texte` | affiché | page d'équipe, carte d'agent : texte du brouillon |
| `fil[].preuve.horodatage` | écarté | horodatage de la dernière transition, non montré par la page |
| `sources[].erreur` | écarté | texte de l'erreur d'une source, non montré par la page |
| `fusions_auto` | affiché | mode autonome : conteneur ; ses sous-champs sont détaillés ci-dessous |
| `fusions_auto.active` | affiché | Scène et Supervision : interrupteur et encadré « Mode autonome » |
| `fusions_auto.suspendue` | affiché | encadré « suspendu », pastille d'en-tête |
| `fusions_auto.depuis` | affiché | encadré : depuis quand le mode est actif |
| `fusions_auto.par` | affiché | encadré : qui a activé le mode |
| `fusions_auto.reserves` | affiché | liste des chemins qui restent à l'utilisateur, regroupés par thème |
| `fusions_auto.reserves_proposees` | affiché | liste proposée à l'activation, quand aucune réserve n'est encore posée |
| `fusions_auto.derniere_fusion` | affiché | encadré actif : dernière fusion faite par l'Assistant |
| `fusions_auto.portee` | affiché | nombre de chemins réservés, dans la ligne repliée et le récap |
| `fusions_auto.chantiers_24h` | affiché | récap : chantiers lancés sur les dernières 24 h |
| `fusions_auto.chantiers_max` | affiché | récap : plafond de chantiers sur 24 h |
| `fusions_auto.decisions` | affiché | récap « Depuis ta dernière visite » : ce que l'Assistant a décidé |
