Summary: Poll iostat and raise alarms for excessive conditions
Name: io-monitor
Version: 1.0
Release: %{tis_patch_ver}%{?_tis_dist}
License: Apache-2.0
Group: base
Packager: Wind River <info@windriver.com>
URL: unknown
Source0: %{name}-%{version}.tar.gz

BuildRequires: python-setuptools
BuildRequires: systemd-units
BuildRequires: systemd-devel
BuildRequires: fm-api
Requires: /bin/systemctl

%description
Poll iostat and raise alarms for excessive conditions

%define local_bindir /usr/bin/
%define local_etc /etc/
%define local_etc_initd /etc/init.d/
%define local_etc_pmond /etc/pmon.d/
%define local_etc_logrotated /etc/logrotate.d/
%define pythonroot /usr/lib64/python2.7/site-packages

%define debug_package %{nil}

%prep
%setup

%build
%{__python} setup.py build

%install
%{__python} setup.py install --root=$RPM_BUILD_ROOT \
                             --install-lib=%{pythonroot} \
                             --prefix=/usr \
                             --install-data=/usr/share \
                             --single-version-externally-managed

install -d -m 755 %{buildroot}%{local_etc}%{name}
install -p -D -m 700 files/io-monitor.conf %{buildroot}%{local_etc}%{name}/io-monitor.conf

install -d -m 755 %{buildroot}%{local_etc_pmond}
install -p -D -m 644 scripts/pmon.d/io-monitor.conf %{buildroot}%{local_etc_pmond}/io-monitor.conf

install -d -m 755 %{buildroot}%{local_etc_initd}
install -p -D -m 700 scripts/init.d/io-monitor-manager %{buildroot}%{local_etc_initd}/io-monitor-manager

install -d -m 755 %{buildroot}%{local_bindir}
install -p -D -m 700 scripts/bin/io-monitor-manager %{buildroot}%{local_bindir}/io-monitor-manager

install -d -m 755 %{buildroot}%{local_etc_logrotated}
install -p -D -m 644 files/io-monitor.logrotate %{buildroot}%{local_etc_logrotated}/io-monitor.logrotate

install -d -m 755 %{buildroot}%{_unitdir}
install -m 644 -p -D files/%{name}-manager.service %{buildroot}%{_unitdir}/%{name}-manager.service

%post
/bin/systemctl enable %{name}-manager.service

%clean
rm -rf $RPM_BUILD_ROOT

# Note: The package name is io-monitor but the import name is io_monitor so
# can't use '%{name}'.
%files
%defattr(-,root,root,-)
%doc LICENSE
%{local_bindir}/*
%{local_etc}%{name}/*
%{local_etc_initd}/*
%{local_etc_pmond}/*
%{_unitdir}/%{name}-manager.service
%dir %{local_etc_logrotated}
%{local_etc_logrotated}/*
%dir %{pythonroot}/io_monitor
%{pythonroot}/io_monitor/*
%dir %{pythonroot}/io_monitor-%{version}.0-py2.7.egg-info
%{pythonroot}/io_monitor-%{version}.0-py2.7.egg-info/*
