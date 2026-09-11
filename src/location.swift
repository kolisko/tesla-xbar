import Foundation
import CoreLocation

// A single reverse lookup of Tesla-provided coordinates, never the Mac's GPS.
// Apple receives the coordinates; no Tesla account data is sent to this helper.
struct Point: Decodable {
    let latitude: Double
    let longitude: Double
}

func finish(_ address: String? = nil) -> Never {
    let output = address.map { ["address": $0] } ?? [:]
    if let data = try? JSONSerialization.data(withJSONObject: output) {
        FileHandle.standardOutput.write(data)
    }
    exit(address == nil ? 1 : 0)
}

let input = FileHandle.standardInput.readDataToEndOfFile()
guard input.count <= 1024,
      let point = try? JSONDecoder().decode(Point.self, from: input),
      point.latitude.isFinite, point.longitude.isFinite,
      (-90...90).contains(point.latitude), (-180...180).contains(point.longitude) else {
    finish()
}

let geocoder = CLGeocoder()
geocoder.reverseGeocodeLocation(CLLocation(latitude: point.latitude, longitude: point.longitude)) { places, error in
    guard error == nil, let place = places?.first else { finish() }
    let street = [place.thoroughfare, place.subThoroughfare].compactMap { $0 }.joined(separator: " ")
    let town = [place.postalCode, place.locality ?? place.subAdministrativeArea].compactMap { $0 }.joined(separator: " ")
    let parts = [street, town, place.administrativeArea ?? "", place.country ?? ""].filter { !$0.isEmpty }
    // A geocoder may only know a locality: do not invent a street or house number.
    guard !parts.isEmpty else { finish() }
    finish(parts.joined(separator: "\n"))
}
DispatchQueue.main.asyncAfter(deadline: .now() + 8) {
    geocoder.cancelGeocode()
    finish()
}
RunLoop.main.run()
