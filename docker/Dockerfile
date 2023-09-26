FROM ubuntu

## Next lines to get ssh to work
RUN apt update \
    && apt install -y firefox \
                      openssh-server \
                      xauth \
    && mkdir /var/run/sshd \
    && mkdir /root/.ssh \
    && chmod 700 /root/.ssh \
    && ssh-keygen -A \
    && sed -i "s/^.*PasswordAuthentication.*$/PasswordAuthentication no/" /etc/ssh/sshd_config \
    && sed -i "s/^.*X11Forwarding.*$/X11Forwarding yes/" /etc/ssh/sshd_config \
    && sed -i "s/^.*X11UseLocalhost.*$/X11UseLocalhost no/" /etc/ssh/sshd_config \
    && grep "^X11UseLocalhost" /etc/ssh/sshd_config || echo "X11UseLocalhost no" >> /etc/ssh/sshd_config

ARG PUB_KEY
RUN echo "$PUB_KEY" >> /root/.ssh/authorized_keys

RUN apt-get install -y \
  python3 \
  python2 \
  python-is-python3 \
  git \
  vim \
  sudo


RUN useradd -ms /bin/bash dockeruser && echo "dockeruser:dockeruser" | chpasswd && adduser dockeruser sudo

# Ensure sudo group users are not 
# asked for a password when using 
# sudo command by ammending sudoers file
RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

USER dockeruser
WORKDIR /home/dockeruser

RUN echo 'alias ll="ls -lh"' >> ~/.bashrc
RUN echo 'alias lll="ls -lah"' >> ~/.bashrc
RUN echo 'export PS1="[DOCKER] \w/ $ "' >> ~/.bashrc
RUN touch ~/.sudo_as_admin_successful


ADD https://gist.githubusercontent.com/simonista/8703722/raw/d08f2b4dc10452b97d3ca15386e9eed457a53c61/.vimrc ~/.vimrc

USER root

RUN echo "AllowUsers dockeruser root" >> /etc/ssh/sshd_config

ENTRYPOINT ["sh", "-c", "/usr/sbin/sshd && tail -f /dev/null"]