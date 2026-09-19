-- Schéma du logiciel de gestion de cabinet « existant » (simulé).
-- Volontairement daté : noms abrégés en majuscules, codes à une ou deux lettres,
-- peu de contraintes, dates parfois vides — comme dans beaucoup de logiciels métier.

DROP TABLE IF EXISTS T_CORRESPONDANCE, T_DOCUMENT, T_INTERVENANT, T_DOSSIER_AVOCAT,
    T_DOSSIER, T_CONTACT, T_CLIENT, T_AVOCAT CASCADE;

CREATE TABLE T_AVOCAT (
    AV_ID          INTEGER PRIMARY KEY,
    AV_INITIALES   VARCHAR(4),
    AV_NOM         VARCHAR(60),
    AV_PRENOM      VARCHAR(60),
    AV_EMAIL       VARCHAR(120),
    AV_FONCTION    VARCHAR(10),       -- ASSOCIE / COLLAB / JURISTE / ASSIST
    AV_ACTIF       CHAR(1) DEFAULT 'O'
);

CREATE TABLE T_CLIENT (
    CLI_ID         INTEGER PRIMARY KEY,
    CLI_CODE       VARCHAR(10),
    CLI_TYPE       CHAR(2),           -- PM = personne morale, PP = personne physique
    CLI_RAISON_SOC VARCHAR(150),      -- PM uniquement
    CLI_FORME      VARCHAR(10),
    CLI_NOM        VARCHAR(60),       -- PP uniquement
    CLI_PRENOM     VARCHAR(60),
    CLI_RCCM       VARCHAR(40),
    CLI_NINEA      VARCHAR(20),
    CLI_ADRESSE    VARCHAR(200),
    CLI_VILLE      VARCHAR(40),
    CLI_TEL        VARCHAR(30),
    CLI_EMAIL      VARCHAR(120),
    CLI_DT_CREA    DATE,
    CLI_OBS        TEXT               -- champ libre
);

CREATE TABLE T_CONTACT (
    CT_ID          INTEGER PRIMARY KEY,
    CLI_ID         INTEGER,
    CT_NOM         VARCHAR(60),
    CT_PRENOM      VARCHAR(60),
    CT_FONCTION    VARCHAR(80),
    CT_EMAIL       VARCHAR(120),
    CT_TEL         VARCHAR(30)
);

CREATE TABLE T_DOSSIER (
    DOS_ID         INTEGER PRIMARY KEY,
    DOS_NUM        VARCHAR(20),
    CLI_ID         INTEGER,
    DOS_INTITULE   VARCHAR(250),
    DOS_TYPE       CHAR(3),           -- CTX = contentieux, CSL = conseil
    DOS_MATIERE    VARCHAR(10),       -- RECOUV / COMM / BAIL / SOC / CONTRAT
    DOS_STATUT     CHAR(2),           -- EC = en cours, CL = clos, AR = archivé
    DOS_DT_OUV     DATE,
    DOS_DT_CLO     DATE,
    DOS_JURIDICTION VARCHAR(120),
    DOS_NUM_RG     VARCHAR(40),
    DOS_ENJEU      NUMERIC(15, 0),    -- FCFA
    DOS_CONFIDENTIEL CHAR(1) DEFAULT 'N',
    DOS_RESP_AV_ID INTEGER
);

CREATE TABLE T_DOSSIER_AVOCAT (
    DOS_ID         INTEGER,
    AV_ID          INTEGER,
    DA_ROLE        VARCHAR(10),       -- RESP / COLLAB / JURISTE / ASSIST
    PRIMARY KEY (DOS_ID, AV_ID)
);

CREATE TABLE T_INTERVENANT (
    INT_ID         INTEGER PRIMARY KEY,
    DOS_ID         INTEGER,
    INT_QUALITE    VARCHAR(6),        -- ADV / AVADV / HUIS / TIERS
    INT_NOM        VARCHAR(150),
    INT_ADRESSE    VARCHAR(200),
    INT_EMAIL      VARCHAR(120),
    INT_TEL        VARCHAR(30)
);

CREATE TABLE T_DOCUMENT (
    DOC_ID         INTEGER PRIMARY KEY,
    DOS_ID         INTEGER,
    DOC_LIBELLE    VARCHAR(250),
    DOC_CATEG      VARCHAR(30),
    DOC_FICHIER    VARCHAR(250),      -- chemin relatif sur le serveur de fichiers
    DOC_DT         DATE,
    DOC_SENS       CHAR(1),           -- E = entrant, S = sortant, I = interne
    DOC_AUTEUR     VARCHAR(150)
);

CREATE TABLE T_CORRESPONDANCE (
    COR_ID         INTEGER PRIMARY KEY,
    DOS_ID         INTEGER,           -- NULL = pas encore classée dans un dossier
    COR_TYPE       VARCHAR(10),       -- MAIL / COURRIER / TEL
    COR_SENS       CHAR(1),
    COR_DATE       TIMESTAMP,
    COR_EXPED      VARCHAR(200),
    COR_DEST       VARCHAR(500),      -- adresses séparées par « ; »
    COR_OBJET      VARCHAR(250),
    COR_CORPS      TEXT,
    COR_PJ         VARCHAR(200)       -- DOC_ID séparés par « ; »
);
