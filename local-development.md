# Local Development Environment Setup

This guide explains how to set up and run the project locally using Docker (with Colima).

## Prerequisites

This project utilizes AI models and requires significant system resources. Ensure Docker has adequate resources allocated. Here's a recommended configuration using Colima:

```sh
colima start --cpu 7 --memory 16 --disk 55
```

## Building Docker Images

After making changes to the source code, rebuild the Docker images using the following commands.

### Backend Image

Navigate to the backend directory and build the backend image:

```sh
cd backend
docker build \
  --no-cache \
  --file Dockerfile \
  --tag onyx-backend:v0.0.1 .
```

### Frontend Image

From the project's root directory, build the frontend image:

```sh
cd web
docker build \
  --no-cache \
  --file Dockerfile \
  --build-arg NODE_OPTIONS="--max-old-space-size=8192" \
  --tag onyx-frontend:v0.0.1 .
```

## Running Services with Docker Compose

Update the `docker-compose.dev.yml` file located at `./deployment/docker_compose/` to use the newly built images. Then start the services with the following command:

```sh
IMAGE_TAG=v0.28.1 docker compose -f docker-compose.dev.yml -p onyx-stack up -d
```

This command will start all the necessary services. After a few minutes, the UI should be accessible at [http://localhost:3000](http://localhost:3000).

## Future Improvements

Currently, the backend and frontend services require building Docker images for every change, which slows the feedback loop. Exploring a setup to run these services natively without rebuilding Docker images could significantly improve development efficiency.
