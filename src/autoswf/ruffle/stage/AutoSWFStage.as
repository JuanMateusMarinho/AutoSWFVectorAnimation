package {
    import flash.display.Loader;
    import flash.display.MovieClip;
    import flash.events.Event;
    import flash.events.UncaughtErrorEvent;
    import flash.geom.ColorTransform;
    import flash.system.ApplicationDomain;
    import flash.system.LoaderContext;
    import flash.text.TextField;
    import flash.text.TextFieldAutoSize;
    import flash.text.TextFormat;
    import flash.utils.ByteArray;
    import flash.utils.Dictionary;

    /** AutoSWF's test stage for Ruffle. It stands in for AQW's Game root (stage.getChildAt(0)): it has the world's
     *  flags and mcSetColor, loads the embedded armor and puts it on an avatar stand-in (AutoSWFAvatar). */
    public class AutoSWFStage extends MovieClip {
        public var world:Object = {bitWalk: true};
        public var settings:Object;
        public var colors:Object;
        public var gender:String;
        public var avatar:AutoSWFAvatar;
        public var face:MovieClip;
        public var status:TextField;
        public var armorError:String;
        private var colored:Dictionary = new Dictionary(true);
        private var loader:Loader;
        private var domain:ApplicationDomain;

        public function AutoSWFStage() {
            super();
            var json:ByteArray = new AutoSWFStageSettings();
            settings = JSON.parse(json.readUTFBytes(json.length));
            colors = settings.colors;
            gender = settings.genders.length > 0 ? settings.genders[0] : "M";
            status = new TextField();
            status.defaultTextFormat = new TextFormat("_sans", 12, 0xFFFFFF);
            status.autoSize = TextFieldAutoSize.LEFT;
            status.x = 8;
            status.y = 8;
            status.selectable = false;
            addChild(status);
            setStatus("Loading the armor…");
            loaderInfo.uncaughtErrorEvents.addEventListener(UncaughtErrorEvent.UNCAUGHT_ERROR, onUncaught);
            var armor:ByteArray = new AutoSWFArmorBytes();
            var context:LoaderContext = new LoaderContext(false, ApplicationDomain.currentDomain);
            context.allowCodeImport = true;
            loader = new Loader();
            loader.uncaughtErrorEvents.addEventListener(UncaughtErrorEvent.UNCAUGHT_ERROR, onUncaught);
            loader.contentLoaderInfo.addEventListener(Event.COMPLETE, onArmor);
            loader.loadBytes(armor, context);
        }

        private function onArmor(e:Event):void {
            domain = loader.contentLoaderInfo.applicationDomain;
            showAvatar();
            if (loaderInfo.parameters.selftest == "1") new AutoSWFSelfTest(this).start();
        }

        /** A fresh avatar wearing the armor of the current gender, playing Idle. */
        public function showAvatar():void {
            if (avatar != null) removeChild(avatar);
            avatar = new AutoSWFAvatar(settings.slots, settings.head[gender] || {});
            avatar.onError = armorStopped;
            avatar.x = 380;
            avatar.y = 470;
            addChildAt(avatar, 0);
            try {
                face = avatar.mcChar.wear(domain, settings.link, gender);
            } catch (err:Error) {
                armorStopped(err.message);
            }
            avatar.playLabel("Idle");
            if (armorError == null) setStatus("Idle");
        }

        public function armorStopped(message:String):void {
            armorError = message;
            setStatus("The armor's code stopped: " + message);
            log("armor error: " + message);
        }

        private function onUncaught(e:UncaughtErrorEvent):void {
            e.preventDefault();
            armorStopped(e.error is Error ? Error(e.error).message : String(e.error));
        }

        /** AQW's Game.mcSetColor: the clip becomes one flat tint of the player's color, shaded (Light +100, Dark -50
         *  with Skin red -25, Darker -125); remembered so a color change re-tints it. */
        public function mcSetColor(clip:MovieClip, location:String, shade:String):void {
            colored[clip] = [location, shade];
            tint(clip, location, shade);
        }

        public function setPlayerColor(location:String, rgb:uint):void {
            colors[location] = rgb;
            for (var key:Object in colored) {
                if (colored[key][0] == location) tint(MovieClip(key), location, colored[key][1]);
            }
        }

        private function tint(clip:MovieClip, location:String, shade:String):void {
            var rgb:uint = uint(colors[location]);
            var s:String = String(shade).toUpperCase();
            var offset:int = s == "LIGHT" ? 100 : s == "DARK" ? -50 : s == "DARKER" ? -125 : 0;
            var red:int = s == "DARK" && location == "Skin" ? -25 : offset;
            clip.transform.colorTransform = new ColorTransform(0, 0, 0, 1, ((rgb >> 16) & 255) + red,
                ((rgb >> 8) & 255) + offset, (rgb & 255) + offset, 0);
        }

        public function setStatus(text:String):void {
            status.text = text;
        }

        public function log(text:String):void {
            trace("AUTOSWF " + text);
        }
    }
}
