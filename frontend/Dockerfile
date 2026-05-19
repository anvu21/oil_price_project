FROM node:20-alpine

WORKDIR /app

# Install dependencies first (cached layer)
COPY package.json package-lock.json* ./
RUN npm install

# Copy source (overridden by volume mount in docker-compose for HMR)
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
