#!env bash
docker build -t test --build-arg PUB_KEY="$(cat ~/.ssh/id_rsa.pub)" . &&
  docker run -it --rm -p 2150:22 test