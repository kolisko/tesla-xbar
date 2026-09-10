package main

import (
	"context"
	"testing"

	"github.com/teslamotors/vehicle-command/pkg/vehicle"
)

func TestXBarClimateKeeperMode(t *testing.T) {
	for value, expected := range map[string]vehicle.ClimateKeeperMode{
		"off": vehicle.ClimateKeeperModeOff, "on": vehicle.ClimateKeeperModeOn,
		"dog": vehicle.ClimateKeeperModeDog, "camp": vehicle.ClimateKeeperModeCamp,
	} {
		actual, err := xbarKeeperMode(value)
		if err != nil || actual != expected {
			t.Fatalf("%s: mode %v, error %v", value, actual, err)
		}
	}
	command := commands["climate-keeper"]
	if command == nil || !command.requiresAuth {
		t.Fatal("climate mode must require signing authentication")
	}
	for _, invalid := range []string{"", "3", "pet", "CAMP", "camp;anything"} {
		// A nil vehicle proves invalid input never reaches a vehicle method.
		if err := command.handler(context.Background(), nil, nil, map[string]string{"MODE": invalid}); err == nil {
			t.Fatalf("accepted invalid mode %q", invalid)
		}
	}
}
