# ==========================================
# Étape 1 : Compilation de l'application React
# ==========================================
FROM node:20-alpine AS builder

WORKDIR /app

# Installation des dépendances avec cache de couche Docker
COPY package*.json ./
RUN npm ci || npm install

# Copier le code source du frontend
COPY . .

# Compiler les fichiers statiques de production (génère le dossier /app/dist)
RUN npm run build

# ==========================================
# Étape 2 : Serveur de distribution Nginx
# ==========================================
FROM nginx:alpine

# Nettoyer les fichiers de configuration par défaut de Nginx
RUN rm -rf /usr/share/nginx/html/*

# Copier les fichiers statiques compilés depuis l'étape précédente
COPY --from=builder /app/dist /usr/share/nginx/html

# Injecter une configuration Nginx robuste gérant le routage SPA (Single Page Application)
RUN echo 'server { \
    listen 80; \
    location / { \
        root /usr/share/nginx/html; \
        index index.html index.htm; \
        try_files $uri $uri/ /index.html; \
    } \
}' > /etc/nginx/conf.d/default.conf

# Exposer le port HTTP standard
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]