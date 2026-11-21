// App-owned radio and a bounded rigctld facade. Independent of
// Station/audio lifetime; Station borrows a backend while it reserves the rig.
#pragma once

#include <QObject>
#include <QHostAddress>
#include <QTcpServer>
#include <QTimer>
#include <QString>
#include <memory>
#include <optional>

class QSettings;

#include "rig/backend.hpp"
#include "rig/controller.hpp"

namespace data2g::app {
// Shared setting names for QML and desktop front ends. The standalone daemon
// is enabled by being launched; it accepts the same port as a CLI option.
struct RigServerSettings { bool enabled = false; quint16 port = 4532; QString listen = "127.0.0.1"; };
RigServerSettings load_rig_server_settings(QSettings& settings);
void save_rig_server_settings(QSettings& settings, const RigServerSettings& config);
struct SharedRadio;
class RigService : public QObject {
public:
    // Port 0 selects an ephemeral port (tests). LAN binding requires an explicit address.
    explicit RigService(std::unique_ptr<rig::RigBackend> backend, quint16 port = 4532,
                        QHostAddress address = QHostAddress(QHostAddress::LocalHost));
    ~RigService() override;
    quint16 port() const { return server_.serverPort(); }
    std::optional<double> frequency() const;
    QString status() const;
    // Qt thread only. Reserve before Station starts any audio. Conflicting
    // external writes/PTT fail busy until release, which follows Station stop.
    void reserve_modem();
    void release_modem();
    std::unique_ptr<rig::RigBackend> modem_backend();
    void stop();
    bool wait_for_shutdown(double seconds);
private:
    struct Client;
    void accept();
    void read(const std::shared_ptr<Client>& client);
    void process(const std::shared_ptr<Client>& client);
    void disconnect(const std::shared_ptr<Client>& client);
    std::shared_ptr<SharedRadio> radio_;
    QTcpServer server_;
    QTimer timer_;
    struct Clients;
    std::unique_ptr<Clients> clients_;
};
}  // namespace data2g::app
