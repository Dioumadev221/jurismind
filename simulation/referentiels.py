"""Référentiels servant à générer un cabinet d'avocats sénégalais fictif.

Toutes les personnes, sociétés et adresses sont inventées. Les domaines email
utilisent le TLD réservé `.example` pour ne jamais tomber sur un vrai domaine.
"""

CABINET_NOM = "Cabinet Téranga Avocats"
CABINET_DOMAINE = "teranga-avocats.example"
CABINET_ADRESSE = "Immeuble Kébé, 12 avenue Léopold Sédar Senghor, Plateau, Dakar"

PRENOMS_H = [
    "Mamadou",
    "Moussa",
    "Ibrahima",
    "Cheikh",
    "Abdoulaye",
    "Ousmane",
    "Modou",
    "Aliou",
    "Babacar",
    "Pape",
    "Serigne",
    "Amadou",
    "Omar",
    "Lamine",
    "Souleymane",
    "Malick",
    "El Hadji",
    "Alassane",
    "Mouhamed",
    "Idrissa",
]
PRENOMS_F = [
    "Fatou",
    "Aminata",
    "Aïssatou",
    "Mariama",
    "Awa",
    "Khady",
    "Ndeye",
    "Coumba",
    "Astou",
    "Rokhaya",
    "Sokhna",
    "Adama",
    "Dieynaba",
    "Marième",
    "Binta",
    "Yacine",
    "Seynabou",
    "Oumy",
]
NOMS = [
    "Diop",
    "Ndiaye",
    "Fall",
    "Sow",
    "Diallo",
    "Ba",
    "Sarr",
    "Faye",
    "Gueye",
    "Mbaye",
    "Seck",
    "Thiam",
    "Cissé",
    "Kane",
    "Sy",
    "Niang",
    "Diouf",
    "Mbengue",
    "Camara",
    "Touré",
    "Sène",
    "Lo",
    "Wade",
    "Dieng",
    "Ndour",
    "Diagne",
    "Samb",
    "Badji",
    "Sagna",
    "Tall",
]

# Ville → code utilisé dans les numéros RCCM.
VILLES = {
    "Dakar": "DKR",
    "Thiès": "THS",
    "Saint-Louis": "STL",
    "Kaolack": "KLK",
    "Ziguinchor": "ZIG",
    "Mbour": "MBR",
    "Rufisque": "RUF",
    "Touba": "TBA",
}
# Pondération : la majorité des clients d'un cabinet dakarois sont à Dakar.
POIDS_VILLES = [60, 8, 5, 5, 4, 7, 7, 4]

QUARTIERS_DAKAR = [
    "Plateau",
    "Point E",
    "Mermoz",
    "Almadies",
    "Sacré-Cœur",
    "Médina",
    "Liberté 6",
    "Ouakam",
    "Hann Maristes",
    "HLM",
    "Parcelles Assainies",
    "Yoff",
    "Fann Résidence",
    "Zone industrielle",
]
RUES = [
    "rue Carnot",
    "avenue Blaise Diagne",
    "boulevard de la République",
    "rue Mohamed V",
    "avenue Cheikh Anta Diop",
    "route de Rufisque",
    "rue Vincens",
    "avenue Lamine Guèye",
    "rue Félix Faure",
    "VDN",
]

PREFIXES_SOCIETES = [
    "Sénégal",
    "Dakar",
    "Sahel",
    "Téranga",
    "Baobab",
    "Cap-Vert",
    "Atlantique",
    "Ouest Africa",
    "Sine",
    "Casamance",
    "Niayes",
    "Kajoor",
    "Djoloff",
    "Saloum",
]
SECTEURS = {
    "Distribution": "commerce de gros et de détail",
    "Transport": "transport routier de marchandises",
    "BTP": "bâtiment et travaux publics",
    "Import-Export": "négoce international",
    "Agro": "transformation agroalimentaire",
    "Pêche": "pêche et mareyage",
    "Immobilier": "promotion immobilière",
    "Services": "prestations de services aux entreprises",
    "Logistique": "logistique et transit",
    "Textile": "confection textile",
    "Télécom": "services de télécommunications",
    "Énergie": "distribution de produits énergétiques",
    "Pharma": "distribution pharmaceutique",
    "Hôtellerie": "hôtellerie et restauration",
}
FORMES_SOCIETES = ["SARL", "SARL", "SARL", "SA", "SA", "SAS", "SUARL", "GIE"]

JURIDICTIONS = {
    "commerce": "Tribunal de commerce hors classe de Dakar",
    "tgi": "Tribunal de grande instance hors classe de Dakar",
    "instance": "Tribunal d'instance hors classe de Dakar",
    "appel": "Cour d'appel de Dakar",
}

BANQUES = [
    "Banque Atlantique du Sahel",
    "Crédit Téranga",
    "Banque Commerciale du Cap-Vert",
    "Union Bancaire de l'Ouest",
    "Société Financière du Saloum",
]

SIGNATURES_MOBILE = [
    "",
    "",
    "",
    "\n\nEnvoyé de mon iPhone",
    "\n\nEnvoyé depuis mon mobile",
]
