package main

// This CLI adapter is built alongside the pinned Tesla SDK using a Go overlay.
// The SDK already implements signing and the climate-keeper vehicle action.
import (
	"context"
	"fmt"

	"github.com/teslamotors/vehicle-command/pkg/account"
	"github.com/teslamotors/vehicle-command/pkg/vehicle"
)

func xbarKeeperMode(value string) (vehicle.ClimateKeeperMode, error) {
	modes := map[string]vehicle.ClimateKeeperMode{
		"off":  vehicle.ClimateKeeperModeOff,
		"on":   vehicle.ClimateKeeperModeOn,
		"dog":  vehicle.ClimateKeeperModeDog,
		"camp": vehicle.ClimateKeeperModeCamp,
	}
	mode, ok := modes[value]
	if !ok {
		return vehicle.ClimateKeeperModeOff, fmt.Errorf("climate mode must be off, on, dog, or camp")
	}
	return mode, nil
}

func init() {
	commands["climate-keeper"] = &Command{
		help:         "Set climate keeper mode (off, on, dog, camp)",
		requiresAuth: true,
		args:         []Argument{{name: "MODE", help: "off, on, dog, or camp"}},
		handler: func(ctx context.Context, _ *account.Account, car *vehicle.Vehicle, args map[string]string) error {
			mode, err := xbarKeeperMode(args["MODE"])
			if err != nil {
				return err
			}
			return car.SetClimateKeeperMode(ctx, mode, false)
		},
	}
}
