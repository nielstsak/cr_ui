# Use official light nginx alpine image
FROM nginx:alpine

# Copy static frontend HTML file to nginx serve directory
COPY index.html /usr/share/nginx/html/index.html

# Expose HTTP port 80
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
